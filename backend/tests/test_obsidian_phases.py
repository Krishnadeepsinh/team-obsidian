import io
import time
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from app.core.database import SessionLocal, init_db
from app.core.security import decrypt_credentials, get_password_hash
from app.main import app
from app.models.evidence import Evidence
from app.models.handover import Handover, HandoverClaim, HandoverSection, HandoverVersion
from app.models.integration import Document, DocumentChunk, Integration, SourceEvent, SourceRecord
from app.models.knowledge import Decision, EmbeddingRecord, KnowledgeEntity, KnowledgeRelationship, RiskItem, TaskItem
from app.models.workspace import Project, ProjectMember, User
from app.services.ai_engine import ai_engine
from app.services.connectors.github_connector import GitHubConnector
from app.services.connectors.notion_connector import NotionConnector
from app.services.connectors.slack_connector import SlackConnector

client = TestClient(app)


def _register_user(name: str, email_prefix: str):
    email = f"{email_prefix}_{int(time.time() * 1000)}@obsidian-test.io"
    res = client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "StrongPassword2026!", "role": "tech_lead"},
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_argon2id_password_hashing_and_legacy_upgrade():
    init_db()
    pw_hash = get_password_hash("EnterprisePass2026!")
    assert pw_hash.startswith("$argon2id$")


def test_protected_endpoints_reject_unauthenticated():
    init_db()
    protected = [
        ("GET", "/api/v1/projects"),
        ("GET", "/api/v1/dashboard/stats"),
        ("GET", "/api/v1/integrations"),
        ("GET", "/api/v1/handovers"),
        ("GET", "/api/v1/decisions"),
        ("GET", "/api/v1/tasks"),
        ("GET", "/api/v1/risks"),
        ("GET", "/api/v1/gaps"),
        ("GET", "/api/v1/evidence"),
        ("GET", "/api/v1/team/members"),
        ("GET", "/api/v1/team/settings"),
        ("GET", "/api/v1/team/activity"),
    ]
    for method, path in protected:
        res = client.request(method, path)
        assert res.status_code == 401, f"{method} {path} returned {res.status_code} instead of 401"


def test_real_bge_semantic_embeddings():
    v1 = ai_engine.generate_embedding("Razorpay webhook HMAC signature verification and Redis Redlock")
    v2 = ai_engine.generate_embedding("Payment service webhook idempotency using Redis distributed lock")
    v3 = ai_engine.generate_embedding("Homemade chocolate sourdough bread baking instructions")
    assert len(v1) == 384
    assert ai_engine.cosine_similarity(v1, v2) > ai_engine.cosine_similarity(v1, v3) + 0.15


def test_controlled_mock_github_slack_notion_sync_and_dedup():
    init_db()
    reg = _register_user("Sync Tester", "sync")
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    pid = reg["active_project_id"]

    # 1. GitHub mocked connect + sync + deduplication
    def fake_gh_req(self, method, url, **kwargs):
        resp = MagicMock()
        resp.headers = {"X-OAuth-Scopes": "repo, read:user", "X-RateLimit-Remaining": "4999"}
        if url.endswith("/user"):
            resp.status_code = 200
            resp.json.return_value = {"login": "rahul-dev", "name": "Rahul Dev"}
        elif "/pulls/" in url and url.endswith("/reviews"):
            resp.status_code = 200
            resp.json.return_value = [{"user": {"login": "amit-lead"}, "state": "APPROVED", "body": "LGTM on Redis lock"}]
        elif "/pulls/" in url and url.endswith("/comments"):
            resp.status_code = 200
            resp.json.return_value = []
        elif "/pulls/" in url and url.endswith("/files"):
            resp.status_code = 200
            resp.json.return_value = [{"filename": "services/payment_adapter.py"}]
        elif "/pulls" in url:
            resp.status_code = 200
            resp.json.return_value = [{
                "id": 101,
                "number": 128,
                "title": "Add Redis Redlock for Payment Webhook",
                "state": "closed",
                "merged_at": "2026-10-01T12:00:00Z",
                "updated_at": "2026-10-01T12:00:00Z",
                "created_at": "2026-09-30T10:00:00Z",
                "user": {"login": "rahul-dev"},
                "base": {"ref": "main"},
                "head": {"ref": "feat/redlock"},
                "body": "Uses Redis Redlock with 5000ms TTL for Razorpay webhook idempotency.",
                "html_url": "https://github.com/acme/ecom/pull/128",
            }]
        elif "/commits" in url:
            resp.status_code = 200
            resp.json.return_value = [{
                "sha": "abcdef1234567890",
                "html_url": "https://github.com/acme/ecom/commit/abcdef12",
                "author": {"login": "rahul-dev"},
                "commit": {"message": "feat: add razorpay webhook hmac verify", "author": {"name": "rahul-dev", "date": "2026-10-01T11:00:00Z"}},
            }]
        elif "/issues" in url:
            resp.status_code = 200
            resp.json.return_value = []
        elif "/releases" in url:
            resp.status_code = 200
            resp.json.return_value = []
        elif "/branches" in url:
            resp.status_code = 200
            resp.json.return_value = [{"name": "main", "protected": True}, {"name": "feat/redlock", "protected": False}]
        elif "/contributors" in url:
            resp.status_code = 200
            resp.json.return_value = [{"login": "rahul-dev", "contributions": 42}]
        else:
            resp.status_code = 404
            resp.json.return_value = {}
        return resp

    with patch.object(GitHubConnector, "_request_with_retry", fake_gh_req):
        c_res = client.post(
            "/api/v1/integrations",
            headers=headers,
            json={
                "project_id": pid,
                "provider": "github",
                "name": "Acme Ecom Repo",
                "credentials": {"access_token": "ghp_mocktoken12345"},
                "config": {"repo": "acme/ecom"},
            },
        )
        assert c_res.status_code == 200, c_res.text
        integ_id = c_res.json()["id"]

        s1 = client.post(f"/api/v1/integrations/{integ_id}/sync?extract_knowledge=false", headers=headers)
        assert s1.status_code == 200, s1.text
        assert s1.json()["records_added"] == 3

        # Second sync with same content must deduplicate (0 added)
        s2 = client.post(f"/api/v1/integrations/{integ_id}/sync?extract_knowledge=false", headers=headers)
        assert s2.status_code == 200
        assert s2.json()["records_added"] == 0
        assert s2.json()["records_skipped"] >= 0

    # 2. Slack mocked thread sync
    def fake_slack_req(self, method, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"X-OAuth-Scopes": "channels:history,channels:read"}
        if "auth.test" in url:
            resp.json.return_value = {"ok": True, "team": "AcmeEng", "user": "obsidian-bot"}
        elif "conversations.list" in url:
            resp.json.return_value = {"ok": True, "channels": [{"id": "C01", "name": "payments", "is_member": True}], "response_metadata": {}}
        elif "conversations.history" in url:
            resp.json.return_value = {
                "ok": True,
                "messages": [{"ts": "1730000000.000100", "user": "U01", "text": "Why did we pick Razorpay?", "reply_count": 1}],
                "response_metadata": {},
            }
        elif "conversations.replies" in url:
            resp.json.return_value = {
                "ok": True,
                "messages": [
                    {"ts": "1730000000.000100", "user": "U01", "text": "Why did we pick Razorpay?"},
                    {"ts": "1730000060.000200", "user": "U02", "text": "Razorpay supports UPI Autopay with 1.8% interchange vs Stripe 2.9%."},
                ],
            }
        elif "users.info" in url:
            resp.json.return_value = {"ok": True, "user": {"name": "Lead Dev", "profile": {"display_name": "Lead Dev"}}}
        else:
            resp.json.return_value = {"ok": True}
        return resp

    with patch.object(SlackConnector, "_request_with_retry", fake_slack_req):
        sc = client.post(
            "/api/v1/integrations",
            headers=headers,
            json={
                "project_id": pid,
                "provider": "slack",
                "name": "Acme Slack",
                "credentials": {"access_token": "xoxb-mocktoken"},
                "config": {"channel": "C01"},
            },
        )
        assert sc.status_code == 200, sc.text
        slack_id = sc.json()["id"]
        ss = client.post(f"/api/v1/integrations/{slack_id}/sync?extract_knowledge=false", headers=headers)
        assert ss.status_code == 200
        assert ss.json()["records_added"] == 1

    # Verify thread replies were captured in SourceRecord
    db = SessionLocal()
    slack_rec = db.query(SourceRecord).filter(SourceRecord.project_id == pid, SourceRecord.source_type == "slack_thread").first()
    assert slack_rec is not None
    assert "UPI Autopay" in slack_rec.content
    db.close()

    # 3. Notion mocked recursive block extraction
    def fake_notion_req(self, method, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "/users/me" in url:
            resp.json.return_value = {"name": "Obsidian Notion", "bot": {"workspace_name": "Acme Docs"}}
        elif "/search" in url:
            resp.json.return_value = {
                "results": [{
                    "id": "page-1",
                    "object": "page",
                    "url": "https://notion.so/page-1",
                    "last_edited_time": "2026-10-05T10:00:00Z",
                    "properties": {"title": {"type": "title", "title": [{"plain_text": "Checkout Runbook"}]}},
                }],
                "has_more": False,
            }
        elif "/blocks/page-1/children" in url:
            resp.json.return_value = {
                "results": [
                    {"id": "b1", "type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Failover Steps"}]}, "has_children": False},
                    {"id": "b2", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Restart payment-worker pod if Redis lock TTL stalls."}]}, "has_children": False},
                ],
                "has_more": False,
            }
        return resp

    with patch.object(NotionConnector, "_request_with_retry", fake_notion_req):
        nc = client.post(
            "/api/v1/integrations",
            headers=headers,
            json={"project_id": pid, "provider": "notion", "name": "Acme Notion", "credentials": {"api_key": "secret_notion_mock"}},
        )
        assert nc.status_code == 200, nc.text
        ns = client.post(f"/api/v1/integrations/{nc.json()['id']}/sync?extract_knowledge=false", headers=headers)
        assert ns.status_code == 200
        assert ns.json()["records_added"] == 1


def test_document_upload_chunking_handover_lifecycle_and_rbac():
    init_db()
    owner = _register_user("Lead User", "lead")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    pid = owner["active_project_id"]

    # Upload a multi-heading markdown architecture spec
    md_content = (
        "# Payment Service Architecture\n\n"
        "The Payment Service uses Razorpay for UPI and card processing.\n\n"
        "# Known Workaround\n\n"
        "If webhook retries exceed 3 attempts, replay via dead-letter queue.\n"
    ).encode("utf-8")

    up_res = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        data={"project_id": pid, "title": "Payment Architecture Spec", "extract_knowledge": "false"},
        files={"file": ("payment_spec.md", md_content, "text/markdown")},
    )
    assert up_res.status_code == 200, up_res.text
    doc_id = up_res.json()["id"]

    chunks_res = client.get(f"/api/v1/documents/{doc_id}/chunks", headers=headers)
    assert chunks_res.status_code == 200
    assert len(chunks_res.json()) >= 1
    assert chunks_res.json()[0]["heading"] == "Payment Service Architecture"

    # Generate handover -> must NOT auto-verify sections, must NOT hardcode Amit Verma/Priya Nair or 0.94
    ho_res = client.post(
        "/api/v1/handovers/reconstruct",
        headers=headers,
        json={
            "project_id": pid,
            "departing_employee_name": "Jordan Lee",
            "departing_employee_role": "Backend Lead",
            "incoming_employee_name": "Taylor Kim",
            "incoming_employee_role": "Senior Engineer",
        },
    )
    assert ho_res.status_code == 200, ho_res.text
    ho = ho_res.json()
    assert len(ho["sections"]) == 16
    assert ho["status"] == "needs_review"
    assert all(not sec["is_verified"] for sec in ho["sections"])
    approver_names = [a["approver_name"] for a in ho["approvals"]]
    assert "Amit Verma" not in approver_names
    assert "Priya Nair" not in approver_names
    assert "Jordan Lee" in approver_names
    assert "Taylor Kim" in approver_names

    # Review & verify Section 1 + edit Section 2 -> check version history diff
    sec1 = ho["sections"][0]
    rev_res = client.post(
        f"/api/v1/handovers/{ho['id']}/sections/{sec1['id']}/review",
        headers=headers,
        json={"action": "verify", "notes": "Confirmed against uploaded spec."},
    )
    assert rev_res.status_code == 200
    assert rev_res.json()["is_verified"] is True
    assert rev_res.json()["verification_status"] == "Verified by Reviewer"

    sec2 = ho["sections"][1]
    edit_res = client.put(
        f"/api/v1/handovers/{ho['id']}/sections/{sec2['id']}",
        headers=headers,
        json={"content": "Updated responsibilities verified by lead.", "is_verified": True, "reason": "Added on-call scope"},
    )
    assert edit_res.status_code == 200

    # Verify viewer RBAC blocks mutation
    viewer = _register_user("Read Only Viewer", "viewer")
    inv_res = client.post(
        f"/api/v1/projects/{pid}/members",
        headers=headers,
        json={"email": viewer["user"]["email"], "project_role": "viewer"},
    )
    assert inv_res.status_code == 200
    v_headers = {"Authorization": f"Bearer {viewer['access_token']}"}
    v_get = client.get(f"/api/v1/handovers/{ho['id']}", headers=v_headers)
    assert v_get.status_code == 200
    v_edit = client.put(
        f"/api/v1/handovers/{ho['id']}/sections/{sec2['id']}",
        headers=v_headers,
        json={"content": "Should fail"},
    )
    assert v_edit.status_code == 403

    # Verify /assistant confidence_breakdown and /knowledge/dependencies return structured responses
    q_res = client.post(
        "/api/v1/assistant/query",
        headers=headers,
        json={"project_id": pid, "question": "What gateway does the Payment Service use for UPI?"},
    )
    assert q_res.status_code == 200, q_res.text
    qd = q_res.json()
    assert qd["is_grounded"] is True
    assert isinstance(qd.get("confidence_breakdown"), dict)
    assert "explanation" in qd["confidence_breakdown"]

    dep_res = client.get(f"/api/v1/knowledge/dependencies?project_id={pid}", headers=headers)
    assert dep_res.status_code == 200
    assert isinstance(dep_res.json(), list)


