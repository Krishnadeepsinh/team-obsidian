"""Phase 4 backend verification: Paginated Connectors, Confluence Webhook, Durable PipelineJob, Explorer Pushdown & Security."""

import hashlib
import hmac
import json
import uuid
from unittest.mock import MagicMock

from fastapi import Response
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import SessionLocal, init_db
from app.core.pipeline_tracker import pipeline_tracker
from app.core.rate_limiter import get_client_ip
from app.main import app
from app.models.integration import Integration, PipelineJob, SourceEvent, SourceRecord
from app.models.knowledge import Decision, TaskItem
from app.models.workspace import Organization, User
from app.services.connectors.confluence_connector import ConfluenceConnector
from app.services.connectors.gitlab_connector import GitLabConnector
from app.services.connectors.jira_connector import JiraConnector
from app.services.connectors.linear_connector import LinearConnector
from app.services.connectors.sentry_connector import SentryConnector

init_db()
client = TestClient(app)


def _register_user(prefix: str = "p4ent"):
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@phase4ent.io"
    res = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Jordan Enterprise",
            "email": email,
            "password": "StrongPhase4EntPassword2026!",
            "role": "tech_lead",
            "title": "Staff Platform",
            "department": "Infrastructure",
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


def _cleanup(email: str, project_id: str):
    db = SessionLocal()
    try:
        db.query(PipelineJob).filter(PipelineJob.project_id == project_id).delete(synchronize_session=False)
        db.query(Decision).filter(Decision.project_id == project_id).delete(synchronize_session=False)
        db.query(TaskItem).filter(TaskItem.project_id == project_id).delete(synchronize_session=False)
        db.query(SourceRecord).filter(SourceRecord.project_id == project_id).delete(synchronize_session=False)
        db.query(Integration).filter(Integration.project_id == project_id).delete(synchronize_session=False)
        u = db.query(User).filter(User.email == email).first()
        if u:
            org = db.query(Organization).filter(Organization.id == u.org_id).first() if u.org_id else None
            if org:
                db.delete(org)
            db.delete(u)
        db.commit()
    finally:
        db.close()


def _mock_resp(status_code: int, payload, headers=None):
    r = MagicMock()
    r.status_code = status_code
    r.headers = headers or {}
    r.text = json.dumps(payload)[:300] if not isinstance(payload, str) else payload
    r.json = lambda: payload
    return r


def test_connectors_multipage_pagination_and_incremental_cursors():
    # 1. Confluence cursor pagination + watermark skip
    conf = ConfluenceConnector(token="tok")
    conf._resolve_wiki_base = lambda: ("https://acme.atlassian.net/wiki", "https://acme.atlassian.net")
    conf_calls = []

    def conf_req(method, url, headers=None, params=None, **kw):
        conf_calls.append(url)
        if "cursor=p2" not in url:
            return _mock_resp(
                200,
                {
                    "results": [
                        {
                            "id": "101",
                            "title": "Runbook Page 1",
                            "spaceId": "10",
                            "version": {"number": 2, "createdAt": "2026-11-10T10:00:00Z"},
                            "body": {"storage": {"value": "<p>Step 1</p>"}},
                            "_links": {"webui": "/spaces/ENG/pages/101"},
                        }
                    ],
                    "_links": {"next": "/wiki/api/v2/pages?cursor=p2"},
                },
            )
        return _mock_resp(
            200,
            {
                "results": [
                    {
                        "id": "102",
                        "title": "Runbook Page 2",
                        "spaceId": "10",
                        "version": {"number": 1, "createdAt": "2026-11-09T10:00:00Z"},
                        "body": {"storage": {"value": "<p>Step 2</p>"}},
                        "_links": {"webui": "/spaces/ENG/pages/102"},
                    }
                ],
                "_links": {},
            },
        )

    conf._request_with_retry = conf_req
    recs, cur = conf.sync(config={}, sync_cursor=None)
    assert len(recs) == 2
    assert len(conf_calls) == 2
    assert cur["last_page_updated"] == "2026-11-10T10:00:00Z"

    # Second run at watermark stops cleanly
    recs2, _ = conf.sync(config={}, sync_cursor=cur)
    assert len(recs2) == 0

    # 2. Jira nextPageToken multi-page
    jira = JiraConnector(token="tok")
    jira._resolve_api_base = lambda: ("https://api.atlassian.com/ex/jira/1/rest/api/3", "https://acme.atlassian.net")

    def jira_req(method, url, headers=None, json_body=None, **kw):
        if not (json_body or {}).get("nextPageToken"):
            return _mock_resp(
                200,
                {
                    "issues": [
                        {"id": "1", "key": "ENG-1", "fields": {"summary": "Fix auth", "updated": "2026-11-10T09:00:00Z"}}
                    ],
                    "nextPageToken": "tok-page-2",
                    "isLast": False,
                },
            )
        return _mock_resp(
            200,
            {
                "issues": [
                    {"id": "2", "key": "ENG-2", "fields": {"summary": "Add cache", "updated": "2026-11-08T09:00:00Z"}}
                ],
                "isLast": True,
            },
        )

    jira._request_with_retry = jira_req
    j_recs, j_cur = jira.sync(config={"project_key": "ENG"}, sync_cursor=None)
    assert len(j_recs) == 2
    assert j_cur["last_issue_updated"] == "2026-11-10T09:00:00Z"

    # 3. Linear GraphQL cursor pagination
    lin = LinearConnector(token="tok")
    lin_pages = []

    def lin_gql(query, variables=None):
        lin_pages.append(variables.get("after"))
        if not variables.get("after"):
            return {
                "issues": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "cur-2"},
                    "nodes": [{"id": "l1", "identifier": "PLT-1", "title": "Rotate keys", "updatedAt": "2026-11-11T00:00:00Z"}],
                },
                "projects": {"nodes": []},
            }
        return {
            "issues": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [{"id": "l2", "identifier": "PLT-2", "title": "Harden CORS", "updatedAt": "2026-11-09T00:00:00Z"}],
            },
        }

    lin._graphql = lin_gql
    l_recs, l_cur = lin.sync(config={"team_key": "PLT"}, sync_cursor=None)
    assert len(l_recs) == 2
    assert lin_pages == [None, "cur-2"]
    assert l_cur["last_issue_updated"] == "2026-11-11T00:00:00Z"

    # 4. GitLab x-next-page pagination
    gl = GitLabConnector(token="tok")
    gl._get_default_branch = lambda enc: "main"

    def gl_req(method, url, headers=None, params=None, **kw):
        pg = (params or {}).get("page", 1)
        if url.endswith("/merge_requests"):
            if pg == 1:
                return _mock_resp(200, [{"iid": 10, "title": "MR10", "updated_at": "2026-11-11T01:00:00Z"}], headers={"x-next-page": "2"})
            return _mock_resp(200, [{"iid": 9, "title": "MR9", "updated_at": "2026-11-10T01:00:00Z"}], headers={})
        if "/projects/" in url and not any(url.endswith(s) for s in ("/issues", "/commits")):
            return _mock_resp(200, {"id": 1, "default_branch": "main", "visibility": "private"}, headers={})
        return _mock_resp(200, [], headers={})

    gl._request_with_retry = gl_req
    gl_recs, gl_cur = gl.sync(config={"repositories": ["acme/core"]}, sync_cursor=None)
    assert len([r for r in gl_recs if r["source_type"] == "gitlab_mr"]) == 2
    assert gl_cur["projects"]["acme/core"]["last_sync_at"] == "2026-11-11T01:00:00Z"

    # 5. Sentry Link header pagination + lastSeen watermark
    sen = SentryConnector(token="tok", org_slug="acme")

    def sen_req(method, url, headers=None, params=None, **kw):
        if "cursor=next2" not in url:
            return _mock_resp(
                200,
                [{"id": "s1", "shortId": "ACME-1", "title": "TimeoutError", "lastSeen": "2026-11-12T02:00:00Z"}],
                headers={"Link": '<https://sentry.io/api/0/projects/acme/api/issues/?cursor=next2>; rel="next"; results="true"'},
            )
        return _mock_resp(
            200,
            [{"id": "s2", "shortId": "ACME-2", "title": "KeyError", "lastSeen": "2026-11-10T02:00:00Z"}],
            headers={},
        )

    sen._request_with_retry = sen_req
    s_recs, s_cur = sen.sync(config={"projects": ["acme/api"]}, sync_cursor=None)
    assert len(s_recs) == 2
    assert s_cur["last_seen_by_project"]["acme/api"] == "2026-11-12T02:00:00Z"


def test_confluence_webhook_pipeline_jobs_and_explorer_sql_pushdown():
    ctx = _register_user("p4api")
    headers = ctx["headers"]
    project_id = ctx["project_id"]

    try:
        # Create Confluence integration with webhook secret
        db = SessionLocal()
        try:
            integ = Integration(
                project_id=project_id,
                user_id=ctx["user_id"],
                provider="confluence",
                name="Acme Confluence",
                status="connected",
                credentials={"webhook_secret": "conf-secret-456"},
            )
            db.add(integ)
            db.add_all([
                Decision(
                    project_id=project_id,
                    title="Adopt PgBouncer Transaction Pooling",
                    summary="Reduces idle Postgres connections during peak deploys.",
                    reasoning="Avoids max_connections exhaustion under autoscaling.",
                    decision_maker="Priya Nair",
                    date="2026-11-10",
                    confidence=0.92,
                    verification_status="Verified by Reviewer",
                ),
                Decision(
                    project_id=project_id,
                    title="Tentative Cache Eviction Heuristic",
                    summary="Draft proposal for Redis LFU.",
                    reasoning="Needs load test.",
                    decision_maker="Sam Lee",
                    date="2026-11-11",
                    confidence=0.35,
                    verification_status="Needs Human Verification",
                ),
            ])
            db.commit()
            integ_id = integ.id
        finally:
            db.close()

        # 1. Confluence webhook signature validation & event ingestion
        wh_body = json.dumps({
            "event": "page_updated",
            "page": {
                "id": "98765",
                "title": "Zero-Downtime Postgres Migration Runbook",
                "space": {"key": "INFRA"},
                "body": {"storage": {"value": "Run preflight check before switchover."}},
            },
            "user": {"displayName": "Priya Nair"},
        }).encode("utf-8")
        bad_res = client.post(
            f"/api/v1/webhooks/confluence/{integ_id}",
            content=wh_body,
            headers={"X-Hub-Signature-256": "sha256=deadbeef"},
        )
        assert bad_res.status_code == 401

        good_sig = "sha256=" + hmac.new(b"conf-secret-456", wh_body, hashlib.sha256).hexdigest()
        ok_res = client.post(
            f"/api/v1/webhooks/confluence/{integ_id}",
            content=wh_body,
            headers={"X-Hub-Signature-256": good_sig},
        )
        assert ok_res.status_code == 200, ok_res.text
        assert ok_res.json()["records"]["added"] == 1

        # 2. Durable PipelineJob across in-memory cache eviction + HTTP job routes
        pipeline_tracker.update(
            project_id,
            stage="extracting_knowledge",
            message="Extracting Postgres migration runbook nodes...",
            progress=65,
            active=True,
            job_type="integration_sync_extraction",
            integration_id=integ_id,
            details={"records": 1},
        )
        # Evict L1 memory cache to prove DB fallback works cleanly
        pipeline_tracker._jobs.pop(project_id, None)
        recovered = pipeline_tracker.get(project_id)
        assert recovered["active"] is True
        assert recovered["progress"] == 65
        assert recovered["integration_id"] == integ_id

        pipeline_tracker.update(
            project_id,
            stage="completed",
            message="Sync & extraction complete.",
            progress=100,
            active=False,
            job_type="integration_sync_extraction",
            integration_id=integ_id,
        )

        jobs_res = client.get(f"/api/v1/integrations/jobs?project_id={project_id}", headers=headers)
        assert jobs_res.status_code == 200, jobs_res.text
        jobs = jobs_res.json()
        assert len(jobs) >= 1
        assert jobs[0]["status"] == "completed"

        integ_jobs = client.get(f"/api/v1/integrations/{integ_id}/jobs", headers=headers)
        assert integ_jobs.status_code == 200
        assert len(integ_jobs.json()) >= 1

        # 3. /knowledge/explorer SQL pushdown filters & pagination
        exp_res = client.get(
            "/api/v1/knowledge/explorer",
            headers=headers,
            params={
                "project_id": project_id,
                "category": "Decisions",
                "search": "pgbouncer",
                "employee": "priya",
                "verification_status": "verified",
                "min_confidence": 0.8,
                "limit": 5,
                "offset": 0,
            },
        )
        assert exp_res.status_code == 200, exp_res.text
        exp_items = exp_res.json()
        assert len(exp_items) == 1
        assert "PgBouncer" in exp_items[0]["title"]
    finally:
        _cleanup(ctx["email"], project_id)


def test_security_hardening_guards_ip_and_cookie_auth():
    # 1. Secret key & SameSite validation guard
    s = Settings()
    s.APP_ENV = "staging"
    s.SECRET_KEY = "dev-secret-short"
    try:
        s.validate_production_readiness()
        assert False, "Expected weak SECRET_KEY in staging to raise RuntimeError"
    except RuntimeError:
        pass

    s.COOKIE_SAMESITE = "invalid_policy"
    try:
        s.validate_production_readiness()
        assert False, "Expected invalid COOKIE_SAMESITE to raise RuntimeError"
    except RuntimeError:
        pass

    # 2. X-Forwarded-For spoofing rejection
    fake_req = MagicMock()
    fake_req.headers = {"x-forwarded-for": "evil-spoof-string, 203.0.113.9"}
    fake_req.client = MagicMock(host="10.0.0.2")
    assert get_client_ip(fake_req) == "203.0.113.9"

    bad_xff_req = MagicMock()
    bad_xff_req.headers = {"x-forwarded-for": "not-an-ip-at-all"}
    bad_xff_req.client = MagicMock(host="198.51.100.4")
    assert get_client_ip(bad_xff_req) == "198.51.100.4"

    # 3. HttpOnly cookie auth login -> /me -> /logout revocation on isolated TestClient
    local_client = TestClient(app)
    ctx = _register_user("p4cookie")
    try:
        login_res = local_client.post(
            "/api/v1/auth/login",
            json={"email": ctx["email"], "password": "StrongPhase4EntPassword2026!"},
            headers={"X-Use-Session-Cookie": "1"},
        )
        assert login_res.status_code == 200, login_res.text
        set_cookie_hdr = login_res.headers.get("set-cookie", "").lower()
        assert "httponly" in set_cookie_hdr
        assert "samesite=" in set_cookie_hdr

        me_res = local_client.get("/api/v1/auth/me")
        assert me_res.status_code == 200
        assert me_res.json()["email"] == ctx["email"]

        out_res = local_client.post("/api/v1/auth/logout")
        assert out_res.status_code == 200
        assert local_client.get("/api/v1/auth/me").status_code == 401
    finally:
        _cleanup(ctx["email"], ctx["project_id"])
