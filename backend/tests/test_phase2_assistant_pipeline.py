import hashlib
import json
import uuid
from fastapi.testclient import TestClient

from app.core.database import SessionLocal, init_db
from app.core.pipeline_tracker import pipeline_tracker
from app.main import app
from app.models.evidence import Evidence
from app.models.workspace import Organization, ProjectMember, User

init_db()
client = TestClient(app)


def _register(role: str = "tech_lead", prefix: str = "p2asst"):
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@phase2-test.io"
    res = client.post(
        "/api/v1/auth/register",
        json={
            "name": f"{prefix.title()} User",
            "email": email,
            "password": "StrongPhase2Password2026!",
            "role": role,
            "title": "Engineer",
            "department": "Platform",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    return {
        "email": email,
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
        "project_id": data["active_project_id"],
        "user_id": data["user"]["id"],
    }


def _cleanup(*emails: str):
    db = SessionLocal()
    try:
        for em in emails:
            u = db.query(User).filter(User.email == em).first()
            if u:
                org = db.query(Organization).filter(Organization.id == u.org_id).first() if u.org_id else None
                if org:
                    db.delete(org)
                db.delete(u)
        db.commit()
    finally:
        db.close()


def test_phase2_assistant_threads_streaming_promote_and_isolation():
    owner = _register("tech_lead", prefix="p2owner")
    outsider = _register("tech_lead", prefix="p2out")
    viewer = _register("viewer", prefix="p2view")

    try:
        # Seed grounded evidence and add viewer as read-only member on owner's project
        db = SessionLocal()
        try:
            ev = Evidence(
                project_id=owner["project_id"],
                source_type="github_pr",
                source_id=f"pr-{uuid.uuid4().hex[:8]}",
                source_title="ADR-09 Redis Failover Pool Architecture",
                source_url="https://github.com/acme/repo/pull/9",
                source_author="Alice",
                excerpt="We selected Redis Sentinel cluster for session failover with 5s sentinel quorum timeout.",
                ai_interpretation="Redis Sentinel handles automatic session cache failover.",
                verification_status="Verified by Reviewer",
                confidence=0.92,
                content_hash=hashlib.sha256(f"pr-9-{uuid.uuid4().hex}".encode()).hexdigest(),
            )
            db.add(ev)
            db.add(
                ProjectMember(
                    project_id=owner["project_id"],
                    user_id=viewer["user_id"],
                    project_role="viewer",
                    status="active",
                )
            )
            db.commit()
            db.refresh(ev)
            ev_id = ev.id
        finally:
            db.close()

        # 1. Single query auto-creates conversation thread
        q1 = client.post(
            "/api/v1/assistant/query",
            headers=owner["headers"],
            json={
                "project_id": owner["project_id"],
                "question": "How is Redis Sentinel failover configured?",
            },
        )
        assert q1.status_code == 200, q1.text
        d1 = q1.json()
        conv_id = d1["conversation_id"]
        assert conv_id
        assert d1["message_id"]
        assert d1["is_grounded"] is True

        # 2. Multi-turn streaming follow-up appends to same conversation
        stream_res = client.post(
            "/api/v1/assistant/query/stream",
            headers=owner["headers"],
            json={
                "project_id": owner["project_id"],
                "question": "What timeout did Redis Sentinel use?",
                "conversation_id": conv_id,
            },
        )
        assert stream_res.status_code == 200, stream_res.text
        assert stream_res.headers["content-type"].startswith("text/event-stream")
        body_text = stream_res.text
        assert "event: meta" in body_text
        assert "event: token" in body_text
        assert "event: done" in body_text

        # Parse final done payload
        done_lines = body_text.split("event: done")[-1].strip().splitlines()
        data_line = next(l for l in done_lines if l.startswith("data:"))
        done_payload = json.loads(data_line[5:].strip())
        assert done_payload["conversation_id"] == conv_id

        # 3. Conversation list & detail reflect 4 ordered messages (2 user, 2 assistant)
        list_res = client.get(
            f"/api/v1/assistant/conversations?project_id={owner['project_id']}",
            headers=owner["headers"],
        )
        assert list_res.status_code == 200
        convs = list_res.json()
        assert len(convs) == 1
        assert convs[0]["id"] == conv_id
        assert convs[0]["message_count"] == 4

        detail_res = client.get(
            f"/api/v1/assistant/conversations/{conv_id}",
            headers=owner["headers"],
        )
        assert detail_res.status_code == 200
        msgs = detail_res.json()["messages"]
        assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]

        # 4. Cross-user isolation on conversation detail & delete
        outsider_detail = client.get(
            f"/api/v1/assistant/conversations/{conv_id}",
            headers=outsider["headers"],
        )
        assert outsider_detail.status_code == 404

        # 5. Promote assistant answer to Decision and Knowledge Gap (+ viewer forbidden)
        viewer_promote = client.post(
            "/api/v1/assistant/promote",
            headers=viewer["headers"],
            json={
                "project_id": owner["project_id"],
                "target_type": "decision",
                "title": "Unauthorized Viewer Decision",
                "content": "Should fail.",
            },
        )
        assert viewer_promote.status_code == 403

        prom_dec = client.post(
            "/api/v1/assistant/promote",
            headers=owner["headers"],
            json={
                "project_id": owner["project_id"],
                "target_type": "decision",
                "title": "Adopt Redis Sentinel Quorum 5s",
                "content": done_payload["answer"],
                "evidence_ids": [ev_id],
            },
        )
        assert prom_dec.status_code == 200, prom_dec.text
        assert prom_dec.json()["target_type"] == "decision"

        prom_gap = client.post(
            "/api/v1/assistant/promote",
            headers=owner["headers"],
            json={
                "project_id": owner["project_id"],
                "target_type": "gap",
                "title": "Document Redis failover runbook escalation",
                "content": "Need pager escalation steps when Sentinel quorum splits.",
                "severity": "high",
            },
        )
        assert prom_gap.status_code == 200, prom_gap.text
        assert prom_gap.json()["target_type"] == "gap"

        # 6. Delete conversation cleanly removes thread
        del_res = client.delete(
            f"/api/v1/assistant/conversations/{conv_id}",
            headers=owner["headers"],
        )
        assert del_res.status_code == 200
        after_list = client.get(
            f"/api/v1/assistant/conversations?project_id={owner['project_id']}",
            headers=owner["headers"],
        )
        assert after_list.status_code == 200
        assert after_list.json() == []
    finally:
        _cleanup(owner["email"], outsider["email"], viewer["email"])


def test_phase2_pipeline_status_and_isolation():
    owner = _register("tech_lead", prefix="p2pipe")
    outsider = _register("tech_lead", prefix="p2pipeout")
    try:
        # Initially idle
        res_idle = client.get(
            f"/api/v1/projects/{owner['project_id']}/pipeline-status",
            headers=owner["headers"],
        )
        assert res_idle.status_code == 200
        assert res_idle.json()["active"] is False
        assert res_idle.json()["stage"] == "idle"

        # Simulate active extraction update
        pipeline_tracker.update(
            owner["project_id"],
            stage="extracting_knowledge",
            message="Extracting architectural entities...",
            progress=65,
            active=True,
            job_type="document_extraction",
        )
        res_active = client.get(
            f"/api/v1/projects/{owner['project_id']}/pipeline-status",
            headers=owner["headers"],
        )
        assert res_active.status_code == 200
        assert res_active.json()["active"] is True
        assert res_active.json()["progress"] == 65
        assert res_active.json()["stage"] == "extracting_knowledge"

        # Outsider blocked
        res_out = client.get(
            f"/api/v1/projects/{owner['project_id']}/pipeline-status",
            headers=outsider["headers"],
        )
        assert res_out.status_code in (403, 404)
    finally:
        _cleanup(owner["email"], outsider["email"])

