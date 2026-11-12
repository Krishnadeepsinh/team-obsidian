import hashlib
import hmac
import json
import os
import sys
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.core.security import create_access_token, encrypt_credentials, get_password_hash
from app.main import app
from app.models.integration import Integration, SourceRecord
from app.models.knowledge import Dependency, KnowledgeEntity
from app.models.workspace import Organization, Project, ProjectMember, User, Workspace
from app.services.connectors import (
    ConfluenceConnector,
    ConnectorError,
    GitHubConnector,
    GitLabConnector,
    JiraConnector,
    LinearConnector,
    NotionConnector,
    SentryConnector,
    SlackConnector,
    get_connector_class,
)
from app.services.connectors._atlassian import flatten_adf, html_to_clean_text, validate_external_https_url
from app.services.email_service import email_service

client = TestClient(app)


class _DummyResp:
    def __init__(self, status_code: int, payload=None, text: str = "", headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or (json.dumps(self._payload) if isinstance(self._payload, (dict, list)) else str(self._payload))
        self.headers = headers or {}

    def json(self):
        return self._payload


def _setup_project_context():
    init_db()
    db = SessionLocal()
    tag = uuid.uuid4().hex[:10]
    org = Organization(name=f"Plat Org {tag}", slug=f"plat-org-{tag}", tier="standard")
    db.add(org)
    db.flush()

    ws = Workspace(org_id=org.id, name="Plat Workspace", slug=f"plat-ws-{tag}")
    db.add(ws)
    db.flush()

    owner = User(
        org_id=org.id,
        personal_workspace_id=ws.id,
        email=f"plat_owner_{tag}@example.com",
        name="Platform Owner",
        role="tech_lead",
        password_hash=get_password_hash("StrongPass2026!"),
    )
    db.add(owner)
    db.flush()

    proj = Project(
        workspace_id=ws.id,
        name=f"Platform Project {tag}",
        slug=f"plat-proj-{tag}",
        description="Multi-provider test project",
    )
    db.add(proj)
    db.flush()
    db.add(ProjectMember(project_id=proj.id, user_id=owner.id, project_role="tech_lead", status="active"))
    db.commit()

    token = create_access_token({
        "sub": owner.id,
        "email": owner.email,
        "role": owner.role,
        "workspace_id": ws.id,
        "project_id": proj.id,
    })
    return db, proj.id, owner.id, {"Authorization": f"Bearer {token}"}


def test_connector_registry_and_capabilities():
    expected = {
        "github": GitHubConnector,
        "slack": SlackConnector,
        "notion": NotionConnector,
        "jira": JiraConnector,
        "confluence": ConfluenceConnector,
        "linear": LinearConnector,
        "gitlab": GitLabConnector,
        "sentry": SentryConnector,
    }
    for name, cls in expected.items():
        assert get_connector_class(name) is cls

    res = client.get("/api/v1/auth/capabilities")
    assert res.status_code == 200
    body = res.json()
    assert set(expected.keys()).issubset(set(body["oauth_providers"].keys()))


def test_ssrf_url_guard_and_atlassian_content_parsers():
    for bad in [
        "http://example.atlassian.net",
        "https://localhost/rest",
        "https://127.0.0.1/rest",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.5/api",
        "https://internal.local/api",
    ]:
        with pytest.raises(ConnectorError):
            validate_external_https_url(bad)

    assert validate_external_https_url("https://acme.atlassian.net/") == "https://acme.atlassian.net"

    adf = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Migrate payment service "}]},
            {"type": "bulletList", "content": [{"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Rotate webhook key"}]}]}]},
        ],
    }
    flat = flatten_adf(adf)
    assert "Migrate payment service" in flat
    assert "Rotate webhook key" in flat

    cleaned = html_to_clean_text("<h1>ADR-04</h1><p>Use Postgres &amp; pgvector.</p><script>alert(1)</script>")
    assert "ADR-04" in cleaned
    assert "Use Postgres & pgvector." in cleaned
    assert "alert(1)" not in cleaned


def test_email_service_uses_resend_onboarding_when_from_is_local(monkeypatch):
    captured = {}

    def _fake_post(url, headers=None, json=None, timeout=10):
        captured["url"] = url
        captured["from"] = json["from"]
        captured["to"] = json["to"]
        return _DummyResp(200, {"id": "email_123"})

    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_key_123")
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "noreply@teamobsidian.local")
    with patch("app.services.email_service.requests.post", side_effect=_fake_post):
        result = email_service.send_email("user@example.com", "Reset", "<p>Hi</p>", "Hi")
    assert result["delivered"] is True
    assert captured["from"] == "TEAM OBSIDIAN <onboarding@resend.dev>"


def test_jira_oauth_and_sync():
    conn = JiraConnector(token="https://acme.atlassian.net|dev@acme.com|ATATT_test_token")
    assert conn.auth_mode == "basic"
    assert "Basic " in conn.headers["Authorization"]

    def fake_request(method, url, headers=None, params=None, json_body=None, data=None, timeout=12):
        if url.endswith("/project/search"):
            return _DummyResp(200, {"values": [{"id": "10001", "key": "ENG", "name": "Engineering", "projectTypeKey": "software"}]})
        if url.endswith("/search/jql"):
            return _DummyResp(200, {
                "issues": [{
                    "id": "200",
                    "key": "ENG-42",
                    "fields": {
                        "summary": "Harden billing webhook replay check",
                        "status": {"name": "In Progress"},
                        "priority": {"name": "High"},
                        "issuetype": {"name": "Bug"},
                        "project": {"key": "ENG"},
                        "assignee": {"displayName": "Asha Patel"},
                        "reporter": {"displayName": "Dev Lead"},
                        "updated": "2026-11-10T10:15:00.000+0000",
                        "labels": ["security", "payments"],
                        "components": [{"name": "billing-api"}],
                        "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Reject stale signatures."}]}]},
                        "comment": {"comments": [{"author": {"displayName": "Reviewer"}, "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "LGTM"}]}]}}]},
                    },
                }]
            })
        return _DummyResp(404)

    with patch.object(JiraConnector, "_request_with_retry", side_effect=fake_request):
        projs = conn.list_projects()
        assert projs[0]["key"] == "ENG"
        records, cursor = conn.sync(config={"projects": ["ENG"]})

    assert len(records) == 1
    assert records[0]["source_type"] == "jira_issue"
    assert records[0]["external_id"] == "jira#ENG-42"
    assert "Reject stale signatures." in records[0]["content"]
    assert cursor["last_issue_updated"] == "2026-11-10T10:15:00.000+0000"


def test_confluence_spaces_and_sync():
    conn = ConfluenceConnector(token="oauth_tok", cloud_id="cloud-99", site_url="https://acme.atlassian.net")

    def fake_request(method, url, headers=None, params=None, json_body=None, data=None, timeout=12):
        if "/api/v2/spaces" in url:
            return _DummyResp(200, {"results": [{"id": "77", "key": "ARCH", "name": "Architecture", "type": "global"}]})
        if "/api/v2/pages" in url:
            return _DummyResp(200, {
                "results": [{
                    "id": "9001",
                    "title": "Database Failover Runbook",
                    "spaceId": "77",
                    "version": {"number": 4, "createdAt": "2026-11-11T09:00:00Z", "authorId": "u-1"},
                    "body": {"storage": {"value": "<p>Promote standby replica via pg_ctl.</p>"}},
                    "_links": {"webui": "/spaces/ARCH/pages/9001"},
                }]
            })
        return _DummyResp(404)

    with patch.object(ConfluenceConnector, "_request_with_retry", side_effect=fake_request):
        spaces = conn.list_spaces()
        assert spaces[0]["key"] == "ARCH"
        records, cursor = conn.sync(config={"spaces": ["77"]})

    assert len(records) == 1
    assert records[0]["source_type"] == "confluence_page"
    assert "Promote standby replica via pg_ctl." in records[0]["content"]
    assert cursor["last_page_updated"] == "2026-11-11T09:00:00Z"


def test_linear_auth_headers_and_sync():
    personal = LinearConnector(token="lin_api_secret_123")
    oauth = LinearConnector(token="oauth_access_123")
    assert personal.headers["Authorization"] == "lin_api_secret_123"
    assert oauth.headers["Authorization"] == "Bearer oauth_access_123"

    def fake_request(method, url, headers=None, params=None, json_body=None, data=None, timeout=12):
        q = (json_body or {}).get("query") or ""
        if "teams(first: 50)" in q:
            return _DummyResp(200, {"data": {"teams": {"nodes": [{"id": "t1", "key": "CORE", "name": "Core Platform"}]}}})
        return _DummyResp(200, {
            "data": {
                "issues": {"nodes": [{
                    "id": "iss-1",
                    "identifier": "CORE-15",
                    "title": "Add circuit breaker to auth client",
                    "description": "Prevent cascading timeouts.",
                    "priorityLabel": "Urgent",
                    "url": "https://linear.app/acme/issue/CORE-15",
                    "createdAt": "2026-11-01T00:00:00Z",
                    "updatedAt": "2026-11-12T08:00:00Z",
                    "state": {"name": "In Review", "type": "started"},
                    "team": {"id": "t1", "key": "CORE", "name": "Core Platform"},
                    "assignee": {"name": "Riya"},
                    "creator": {"name": "Lead"},
                    "project": {"id": "p1", "name": "Resilience"},
                    "labels": {"nodes": [{"name": "reliability"}]},
                    "comments": {"nodes": [{"body": "Added exponential backoff", "user": {"name": "Riya"}}]},
                }]},
                "projects": {"nodes": [{"id": "p1", "name": "Resilience", "state": "started", "description": "Q4 reliability", "url": "https://linear.app/acme/project/res", "updatedAt": "2026-11-12T08:00:00Z", "lead": {"name": "Riya"}}]},
            }
        })

    with patch.object(LinearConnector, "_request_with_retry", side_effect=fake_request):
        teams = personal.list_teams()
        assert teams[0]["key"] == "CORE"
        records, cursor = personal.sync(config={"teams": ["CORE"]})

    assert any(r["source_type"] == "linear_issue" and r["external_id"] == "linear#CORE-15" for r in records)
    assert any(r["source_type"] == "linear_project" for r in records)
    assert cursor["last_issue_updated"] == "2026-11-12T08:00:00Z"


def test_gitlab_sync_and_ast_indexing_and_sentry_sync():
    gl = GitLabConnector(token="glpat-abc123")
    assert gl.headers["PRIVATE-TOKEN"] == "glpat-abc123"

    def fake_gl(method, url, headers=None, params=None, json_body=None, data=None, timeout=12):
        if url.endswith("/api/v4/projects/acme%2Fapi"):
            return _DummyResp(200, {"id": 9, "default_branch": "main", "visibility": "private", "web_url": "https://gitlab.com/acme/api"})
        if "/repository/tree" in url:
            return _DummyResp(200, [{"type": "blob", "path": "app/main.py"}])
        if "/repository/files/app%2Fmain.py/raw" in url:
            return _DummyResp(200, text="import fastapi\nfrom sqlalchemy import select\n")
        if "/merge_requests" in url:
            return _DummyResp(200, [{"iid": 11, "title": "Add SSO guard", "state": "merged", "source_branch": "feat/sso", "target_branch": "main", "author": {"username": "krishna"}, "updated_at": "2026-11-12T10:00:00Z", "web_url": "https://gitlab.com/acme/api/-/merge_requests/11"}])
        if url.endswith("/issues"):
            return _DummyResp(200, [{"iid": 4, "title": "Audit CORS headers", "state": "opened", "labels": ["security"], "author": {"username": "krishna"}, "updated_at": "2026-11-12T10:05:00Z", "web_url": "https://gitlab.com/acme/api/-/issues/4"}])
        if "/repository/commits" in url:
            return _DummyResp(200, [{"id": "deadbeef1234", "title": "fix(auth): enforce audience", "message": "fix(auth): enforce audience", "author_name": "krishna", "committed_date": "2026-11-12T10:10:00Z", "web_url": "https://gitlab.com/acme/api/-/commit/deadbeef"}])
        return _DummyResp(404)

    with patch.object(GitLabConnector, "_request_with_retry", side_effect=fake_gl):
        gl_records, _ = gl.sync(config={"repos": ["acme/api"]})

    source_types = {r["source_type"] for r in gl_records}
    assert {"gitlab_repository", "gitlab_ast", "gitlab_mr", "gitlab_issue", "gitlab_commit"}.issubset(source_types)

    # Verify Sentry Connector
    sc = SentryConnector(token="sntryu_token_abc", org_slug="gmiu")

    def fake_sentry(method, url, headers=None, params=None, json_body=None, data=None, timeout=12):
        if url.endswith("/api/0/organizations/"):
            return _DummyResp(200, [{"slug": "gmiu"}])
        if url.endswith("/api/0/organizations/gmiu/projects/"):
            return _DummyResp(200, [{"id": "1", "slug": "backend-api", "name": "Backend API", "platform": "python"}])
        if "/projects/gmiu/backend-api/issues/" in url:
            return _DummyResp(200, [{"id": "888", "shortId": "BACKEND-1A", "title": "TimeoutError: Redis pool exhausted", "culprit": "app/cache.py", "level": "fatal", "status": "unresolved", "count": "47", "userCount": 12, "lastSeen": "2026-11-12T11:00:00Z", "permalink": "https://gmiu.sentry.io/issues/888/"}])
        return _DummyResp(404)

    with patch.object(SentryConnector, "_request_with_retry", side_effect=fake_sentry):
        s_projs = sc.list_projects()
        assert s_projs[0]["full_slug"] == "gmiu/backend-api"
        s_records, _ = sc.sync(config={"projects": ["gmiu/backend-api"]})
    assert len(s_records) == 1
    assert s_records[0]["source_type"] == "sentry_issue"
    assert "Redis pool exhausted" in s_records[0]["content"]


def test_webhook_signatures_for_gitlab_linear_jira_sentry():
    db, project_id, user_id, _ = _setup_project_context()
    try:
        secrets_by_prov = {}
        integ_ids = {}
        for prov in ("gitlab", "linear", "jira", "sentry"):
            sec = f"whsec_{prov}_{uuid.uuid4().hex[:8]}"
            integ = Integration(
                project_id=project_id,
                user_id=user_id,
                provider=prov,
                name=f"{prov.title()} Integration",
                auth_type="oauth",
                auth_status="verified",
                status="connected",
                credentials=encrypt_credentials({"access_token": "tok", "webhook_secret": sec}),
            )
            db.add(integ)
            db.flush()
            secrets_by_prov[prov] = sec
            integ_ids[prov] = integ.id
        db.commit()

        # 1. GitLab token check + valid MR webhook
        bad_gl = client.post(f"/api/v1/webhooks/gitlab/{integ_ids['gitlab']}", json={"object_kind": "push"}, headers={"X-Gitlab-Token": "wrong"})
        assert bad_gl.status_code == 401
        ok_gl = client.post(
            f"/api/v1/webhooks/gitlab/{integ_ids['gitlab']}",
            json={"object_kind": "merge_request", "project": {"path_with_namespace": "acme/api"}, "object_attributes": {"iid": 7, "title": "Enable mTLS", "state": "opened", "description": "Strict TLS"}, "user": {"username": "dev"}},
            headers={"X-Gitlab-Token": secrets_by_prov["gitlab"]},
        )
        assert ok_gl.status_code == 200
        assert ok_gl.json()["records"]["added"] == 1

        # 2. Linear HMAC-SHA256 check
        lin_body = json.dumps({"type": "Issue", "action": "create", "data": {"identifier": "ENG-9", "title": "Fix queue lag", "description": "Increase workers"}}).encode("utf-8")
        lin_sig = hmac.new(secrets_by_prov["linear"].encode("utf-8"), lin_body, hashlib.sha256).hexdigest()
        assert client.post(f"/api/v1/webhooks/linear/{integ_ids['linear']}", content=lin_body, headers={"Linear-Signature": "bad"}).status_code == 401
        ok_lin = client.post(f"/api/v1/webhooks/linear/{integ_ids['linear']}", content=lin_body, headers={"Linear-Signature": lin_sig})
        assert ok_lin.status_code == 200 and ok_lin.json()["records"]["added"] == 1

        # 3. Jira sha256= HMAC check
        jira_body = json.dumps({"webhookEvent": "jira:issue_created", "issue": {"key": "OPS-12", "fields": {"summary": "Deploy Postgres 16", "status": {"name": "Done"}}}}).encode("utf-8")
        jira_sig = "sha256=" + hmac.new(secrets_by_prov["jira"].encode("utf-8"), jira_body, hashlib.sha256).hexdigest()
        ok_jira = client.post(f"/api/v1/webhooks/jira/{integ_ids['jira']}", content=jira_body, headers={"X-Hub-Signature": jira_sig})
        assert ok_jira.status_code == 200 and ok_jira.json()["records"]["added"] == 1

        # 4. Sentry Sentry-Hook-Signature check
        sen_body = json.dumps({"action": "created", "data": {"issue": {"id": "99", "shortId": "API-99", "title": "KeyError: org_id", "culprit": "auth.py", "level": "error"}}}).encode("utf-8")
        sen_sig = hmac.new(secrets_by_prov["sentry"].encode("utf-8"), sen_body, hashlib.sha256).hexdigest()
        ok_sen = client.post(f"/api/v1/webhooks/sentry/{integ_ids['sentry']}", content=sen_body, headers={"Sentry-Hook-Signature": sen_sig})
        assert ok_sen.status_code == 200 and ok_sen.json()["records"]["added"] == 1

        count_rows = db.query(SourceRecord).filter(SourceRecord.project_id == project_id).count()
        assert count_rows == 4
    finally:
        db.close()


def test_oauth_authorize_urls_for_new_providers(monkeypatch):
    _, project_id, _, auth_headers = _setup_project_context()
    monkeypatch.setattr(settings, "ATLASSIAN_CLIENT_ID", "atl_cid")
    monkeypatch.setattr(settings, "ATLASSIAN_CLIENT_SECRET", "atl_csec")
    monkeypatch.setattr(settings, "LINEAR_CLIENT_ID", "lin_cid")
    monkeypatch.setattr(settings, "LINEAR_CLIENT_SECRET", "lin_csec")
    monkeypatch.setattr(settings, "GITLAB_CLIENT_ID", "gl_cid")
    monkeypatch.setattr(settings, "GITLAB_CLIENT_SECRET", "gl_csec")

    for prov, expected_host in [
        ("jira", "https://auth.atlassian.com/authorize"),
        ("confluence", "https://auth.atlassian.com/authorize"),
        ("linear", "https://linear.app/oauth/authorize"),
        ("gitlab", "https://gitlab.com/oauth/authorize"),
    ]:
        res = client.get(f"/api/v1/integrations/oauth/{prov}/authorize", params={"project_id": project_id}, headers=auth_headers)
        assert res.status_code == 200, res.text
        assert res.json()["authorize_url"].startswith(expected_host)

