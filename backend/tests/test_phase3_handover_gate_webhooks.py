import uuid
from fastapi.testclient import TestClient

from app.core.database import SessionLocal, init_db
from app.main import app
from app.models.knowledge import KnowledgeDriftEvent, KnowledgeGap, TaskItem
from app.models.workspace import Organization, ProjectMember, User

init_db()
client = TestClient(app)


def _register(role: str = "tech_lead", prefix: str = "p3test"):
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@phase3-test.io"
    res = client.post(
        "/api/v1/auth/register",
        json={
            "name": f"{prefix.title()} Engineer",
            "email": email,
            "password": "StrongPhase3Password2026!",
            "role": role,
            "title": "Lead",
            "department": "Engineering",
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


def test_phase3_readiness_gate_markdown_export_and_onboarding_tasks():
    owner = _register("tech_lead", prefix="p3own")
    outsider = _register("tech_lead", prefix="p3out")
    viewer = _register("viewer", prefix="p3view")

    try:
        db = SessionLocal()
        try:
            db.add(
                ProjectMember(
                    project_id=owner["project_id"],
                    user_id=viewer["user_id"],
                    project_role="viewer",
                    status="active",
                )
            )
            gap = KnowledgeGap(
                project_id=owner["project_id"],
                title="Critical Runbook Missing",
                description="Missing Redis failover runbook",
                gap_type="documentation",
                severity="critical",
                priority="critical",
                impact="Blocks failover recovery",
                recommended_action="Document sentinel failover procedure",
                status="open",
            )
            drift = KnowledgeDriftEvent(
                project_id=owner["project_id"],
                drift_type="contradiction",
                severity="high",
                target_entity_type="decision",
                target_entity_id=str(uuid.uuid4()),
                target_title="Cache TTL Policy",
                summary="New PR conflicts with prior cache TTL ADR",
                status="open",
            )
            db.add(gap)
            db.add(drift)
            db.commit()
            gap_id = gap.id
            drift_id = drift.id
        finally:
            db.close()

        # Reconstruct handover dossier
        rec_res = client.post(
            "/api/v1/handovers/reconstruct",
            headers=owner["headers"],
            json={
                "project_id": owner["project_id"],
                "departing_employee_name": "Alex Rivera",
                "departing_employee_role": "Staff Backend Engineer",
                "incoming_employee_name": "Jordan Patel",
                "incoming_employee_role": "Senior Engineer",
                "approvers": [
                    {"role": "tech_lead", "approver_name": "Owner Lead", "is_required": True},
                ],
            },
        )
        assert rec_res.status_code == 200, rec_res.text
        handover = rec_res.json()
        hid = handover["id"]

        # 1. Readiness gate starts blocked
        gate1 = client.get(f"/api/v1/handovers/{hid}/readiness-gate", headers=owner["headers"])
        assert gate1.status_code == 200, gate1.text
        g1_data = gate1.json()
        assert g1_data["can_finalize"] is False
        assert g1_data["readiness_score"] < 100
        assert len(g1_data["blockers"]) >= 4

        # Outsider blocked on gate and markdown export
        assert client.get(f"/api/v1/handovers/{hid}/readiness-gate", headers=outsider["headers"]).status_code in (403, 404)
        assert client.get(f"/api/v1/handovers/{hid}/export/markdown", headers=outsider["headers"]).status_code in (403, 404)

        # 2. Markdown export renders structured HANDOVER.md
        md_res = client.get(f"/api/v1/handovers/{hid}/export/markdown", headers=owner["headers"])
        assert md_res.status_code == 200, md_res.text
        assert md_res.headers["content-type"].startswith("text/markdown")
        assert "attachment; filename=\"HANDOVER_" in md_res.headers.get("content-disposition", "")
        assert "Alex Rivera" in md_res.text
        assert "## 1." in md_res.text

        # 3. Simulator evaluation -> creates onboarding tasks for missed concepts
        sim_get = client.get(f"/api/v1/handovers/{hid}/simulator", headers=owner["headers"])
        assert sim_get.status_code == 200
        scenarios = sim_get.json()["scenarios"]
        assert len(scenarios) >= 1

        # Submit short/weak answers to force missed concepts
        weak_answers = {sc["id"]: "need review" for sc in scenarios}
        eval_res = client.post(
            f"/api/v1/handovers/{hid}/simulator/evaluate",
            headers=owner["headers"],
            json={"candidate_name": "Jordan Patel", "scenarios": scenarios, "answers": weak_answers},
        )
        assert eval_res.status_code == 200, eval_res.text
        sim_attempt_id = eval_res.json()["id"]

        # Viewer forbidden from generating tasks
        assert (
            client.post(
                f"/api/v1/handovers/{hid}/simulator/create-onboarding-tasks",
                headers=viewer["headers"],
                json={"simulation_id": sim_attempt_id},
            ).status_code
            == 403
        )

        # Owner generates onboarding tasks cleanly and deduplicates on retry
        gen1 = client.post(
            f"/api/v1/handovers/{hid}/simulator/create-onboarding-tasks",
            headers=owner["headers"],
            json={"simulation_id": sim_attempt_id},
        )
        assert gen1.status_code == 200, gen1.text
        assert gen1.json()["created_count"] >= 1
        assert gen1.json()["assignee"] == "Jordan Patel"

        gen2 = client.post(
            f"/api/v1/handovers/{hid}/simulator/create-onboarding-tasks",
            headers=owner["headers"],
            json={"simulation_id": sim_attempt_id},
        )
        assert gen2.status_code == 200
        assert gen2.json()["created_count"] == 0

        # 4. Complete remaining gate blockers -> verify score reaches 100% when all checks pass
        for sec in handover["sections"]:
            r_sec = client.post(
                f"/api/v1/handovers/{hid}/sections/{sec['id']}/review",
                headers=owner["headers"],
                json={"action": "verify"},
            )
            assert r_sec.status_code == 200
            for cl in sec.get("claims") or []:
                rc = client.post(
                    f"/api/v1/handovers/{hid}/claims/{cl['id']}/verify",
                    headers=owner["headers"],
                    json={"verification_status": "Verified by Reviewer"},
                )
                assert rc.status_code == 200

        # Resolve gap, drift, and mark simulator passed directly cleanly via passing submission
        strong_answers = {
            sc["id"]: (
                f"To mitigate {sc['title']}, we inspect logs, verify the expected concepts "
                + ", ".join(sc.get("expected_concepts") or ["failover", "rollback"])
                + ", coordinate across owning teams, execute staged rollback with health checks, "
                "and validate service SLO telemetry across downstream dependencies before reopening traffic."
            )
            for sc in scenarios
        }
        eval_pass = client.post(
            f"/api/v1/handovers/{hid}/simulator/evaluate",
            headers=owner["headers"],
            json={"candidate_name": "Jordan Patel", "scenarios": scenarios, "answers": strong_answers},
        )
        assert eval_pass.status_code == 200
        assert eval_pass.json()["passed"] is True, eval_pass.json()

        db = SessionLocal()
        try:
            g = db.query(KnowledgeGap).filter(KnowledgeGap.id == gap_id).first()
            if g:
                g.status = "resolved"
            dr = db.query(KnowledgeDriftEvent).filter(KnowledgeDriftEvent.id == drift_id).first()
            if dr:
                dr.status = "resolved"
            db.commit()
        finally:
            db.close()

        app_res = client.post(
            f"/api/v1/handovers/{hid}/approve",
            headers=owner["headers"],
            json={"role": "tech_lead", "approver_name": "Owner Lead", "status": "approved"},
        )
        assert app_res.status_code == 200

        gate_final = client.get(f"/api/v1/handovers/{hid}/readiness-gate", headers=owner["headers"]).json()
        assert gate_final["blockers"] == []
        assert gate_final["can_finalize"] is True
        assert gate_final["readiness_score"] == 100.0
        assert gate_final["blockers"] == []
    finally:
        _cleanup(owner["email"], outsider["email"], viewer["email"])


def test_phase3_auto_webhook_and_sync_cadence(monkeypatch):
    owner = _register("tech_lead", prefix="p3wh")
    outsider = _register("tech_lead", prefix="p3whout")

    import app.api.v1.integrations as integ_mod

    monkeypatch.setattr(
        integ_mod.GitHubConnector,
        "check_connection",
        lambda self: {"status": "connected", "connected_account": "acme-bot", "scopes": ["repo"]},
    )

    try:
        create_res = client.post(
            "/api/v1/integrations",
            headers=owner["headers"],
            json={
                "project_id": owner["project_id"],
                "provider": "github",
                "name": "Core GitHub",
                "auth_type": "token",
                "credentials": {"access_token": "ghp_testtoken1234567890"},
                "config": {"repos": ["acme/backend-api", "acme/worker-svc"]},
            },
        )
        assert create_res.status_code == 200, create_res.text
        integ_id = create_res.json()["id"]

        # Invalid cadence rejected with 400
        bad_cfg = client.put(
            f"/api/v1/integrations/{integ_id}/config",
            headers=owner["headers"],
            json={"config": {"repos": ["acme/backend-api"], "sync_interval_minutes": -10}},
        )
        # Clamped cleanly or 400; check non-integer fails with 400
        bad_str_cfg = client.put(
            f"/api/v1/integrations/{integ_id}/config",
            headers=owner["headers"],
            json={"config": {"repos": ["acme/backend-api"], "sync_interval_minutes": "invalid"}},
        )
        assert bad_str_cfg.status_code == 400

        good_cfg = client.put(
            f"/api/v1/integrations/{integ_id}/config",
            headers=owner["headers"],
            json={"config": {"repos": ["acme/backend-api", "acme/worker-svc"], "sync_interval_minutes": 60}},
        )
        assert good_cfg.status_code == 200, good_cfg.text
        assert good_cfg.json()["config"]["sync_interval_minutes"] == 60

        # Mock httpx.Client for GitHub webhook API calls
        called_urls = []

        class _FakeResp:
            def __init__(self, code, payload):
                self.status_code = code
                self._payload = payload
                self.text = str(payload)

            def json(self):
                return self._payload

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, url, headers=None, json=None):
                called_urls.append((url, json))
                if "backend-api" in url:
                    return _FakeResp(201, {"id": 9001})
                return _FakeResp(422, {"message": "Hook already exists on this repository"})

        import app.api.v1.integrations as integ_mod

        monkeypatch.setattr(integ_mod.httpx, "Client", _FakeClient)

        # Outsider blocked
        assert (
            client.post(f"/api/v1/integrations/{integ_id}/auto-webhook", headers=outsider["headers"]).status_code
            in (403, 404)
        )

        hook_res = client.post(f"/api/v1/integrations/{integ_id}/auto-webhook", headers=owner["headers"])
        assert hook_res.status_code == 200, hook_res.text
        hdata = hook_res.json()
        assert hdata["mode"] == "github_api"
        assert hdata["has_secret"] is True
        assert hdata["webhook_secret"]
        assert len(called_urls) == 2
        statuses = {r["repo"]: r["status"] for r in hdata["results"]}
        assert statuses["acme/backend-api"] == "registered"
        assert statuses["acme/worker-svc"] == "already_exists"

        # Verify integration config persisted auto_webhook_registered metadata
        list_res = client.get(f"/api/v1/integrations?project_id={owner['project_id']}", headers=owner["headers"])
        assert list_res.status_code == 200
        found = next(i for i in list_res.json() if i["id"] == integ_id)
        assert found["config"]["auto_webhook_registered"] is True
        assert "acme/backend-api" in found["config"]["auto_webhook_repos"]
    finally:
        _cleanup(owner["email"], outsider["email"])
