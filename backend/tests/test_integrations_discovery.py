import os
import sys
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.database import SessionLocal, init_db
from app.core.security import create_access_token, create_oauth_state_token, decrypt_credentials, encrypt_credentials, get_password_hash
from app.main import app
from app.models.integration import Integration, SourceEvent, SourceRecord
from app.models.workspace import Organization, Project, ProjectMember, User, Workspace
from app.services.connectors import ConnectorError, GitHubConnector, NotionConnector, SlackConnector

client = TestClient(app)


class _DummyResp:
    def __init__(self, status_code: int, payload: dict | list | None = None, text: str = "", headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or str(self._payload)
        self.headers = headers or {}

    def json(self):
        return self._payload


def _create_isolated_context():
    init_db()
    db = SessionLocal()
    tag = uuid.uuid4().hex[:10]
    org = Organization(name=f"IntTest Org {tag}", slug=f"inttest-org-{tag}", tier="standard")
    db.add(org)
    db.flush()

    ws = Workspace(org_id=org.id, name="IntTest Workspace", slug=f"inttest-ws-{tag}")
    db.add(ws)
    db.flush()

    user = User(
        org_id=org.id,
        personal_workspace_id=ws.id,
        email=f"inttest_{tag}@example.com",
        name="Integration Lead",
        role="tech_lead",
        password_hash=get_password_hash("StrongPass2026!"),
    )
    other = User(
        org_id=org.id,
        personal_workspace_id=ws.id,
        email=f"other_{tag}@example.com",
        name="Outsider User",
        role="developer",
        password_hash=get_password_hash("StrongPass2026!"),
    )
    db.add(user)
    db.add(other)
    db.flush()

    proj = Project(
        workspace_id=ws.id,
        name=f"Integration Test Project {tag}",
        slug=f"int-proj-{tag}",
        description="Isolated project for integration discovery tests",
        status="active",
    )
    db.add(proj)
    db.flush()

    db.add(ProjectMember(project_id=proj.id, user_id=user.id, project_role="tech_lead", status="active"))
    db.commit()

    token = create_access_token({"sub": user.id, "email": user.email, "role": user.role, "project_id": proj.id})
    other_token = create_access_token({"sub": other.id, "email": other.email, "role": other.role})
    res = {
        "headers": {"Authorization": f"Bearer {token}"},
        "other_headers": {"Authorization": f"Bearer {other_token}"},
        "project_id": proj.id,
        "user_id": user.id,
        "org_id": org.id,
    }
    db.close()
    return res


def _cleanup_context(org_id: str, project_id: str):
    db = SessionLocal()
    try:
        integs = db.query(Integration).filter(Integration.project_id == project_id).all()
        for i in integs:
            db.query(SourceEvent).filter(SourceEvent.integration_id == i.id).delete()
            db.query(SourceRecord).filter(SourceRecord.integration_id == i.id).delete()
        db.query(Integration).filter(Integration.project_id == project_id).delete()
        db.query(SourceRecord).filter(SourceRecord.project_id == project_id).delete()
        org = db.query(Organization).filter(Organization.id == org_id).first()
        if org:
            db.delete(org)
        db.commit()
    finally:
        db.close()


def test_github_list_repositories_installations_fallback_and_401():
    connector = GitHubConnector(token="ghu_app_user_token")
    calls = []

    def fake_req(method, url, **kwargs):
        calls.append((method, url, kwargs.get("params")))
        if url.endswith("/user/repos"):
            return _DummyResp(200, [])
        if url.endswith("/user/installations"):
            return _DummyResp(200, {"installations": [{"id": 99}]})
        if url.endswith("/user/installations/99/repositories"):
            return _DummyResp(
                200,
                {
                    "repositories": [
                        {
                            "full_name": "acme-org/payments-core",
                            "private": True,
                            "default_branch": "main",
                            "html_url": "https://github.com/acme-org/payments-core",
                        }
                    ]
                },
            )
        return _DummyResp(404, {})

    with patch.object(connector, "_request_with_retry", side_effect=fake_req):
        repos = connector.list_repositories(max_pages=1)

    assert len(repos) == 1
    assert repos[0]["full_name"] == "acme-org/payments-core"
    assert calls[0][2]["affiliation"] == "owner,collaborator,organization_member"

    with patch.object(connector, "_request_with_retry", return_value=_DummyResp(401, {"message": "Bad credentials"})):
        with pytest.raises(ConnectorError):
            connector.list_repositories(max_pages=1)


def test_github_sync_supports_comma_separated_repos():
    connector = GitHubConnector(token="ghp_test")
    synced = []

    def fake_sync_repo(repo_name, since_iso=None):
        synced.append(repo_name)
        return []

    with patch.object(connector, "sync_repository", side_effect=fake_sync_repo):
        _, cursor = connector.sync(config={"repo": "org/service-a, org/service-b"})

    assert synced == ["org/service-a", "org/service-b"]
    assert "org/service-a" in cursor and "org/service-b" in cursor


def test_slack_list_channels_error_and_multi_channel_sync():
    connector = SlackConnector(token="xoxb-test")
    with patch.object(connector, "_request_with_retry", return_value=_DummyResp(200, {"ok": False, "error": "invalid_auth"})):
        with pytest.raises(ConnectorError, match="invalid_auth"):
            connector.list_channels()

    synced_ids = []
    with (
        patch.object(
            connector,
            "list_channels",
            return_value=[
                {"id": "C111", "name": "eng", "is_member": True},
                {"id": "C222", "name": "ops", "is_member": True},
            ],
        ),
        patch.object(
            connector,
            "sync_channel_messages",
            side_effect=lambda cid, channel_name=None, oldest_ts=None: (synced_ids.append(cid) or [], "1700000.1"),
        ),
    ):
        _, cursor = connector.sync(config={"channels": ["C111", "C222"]})

    assert synced_ids == ["C111", "C222"]
    assert cursor["C111"] == "1700000.1"


def test_notion_list_resources_and_targeted_sync():
    connector = NotionConnector(token="ntn_test")
    search_payload = {
        "results": [
            {
                "object": "page",
                "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "url": "https://notion.so/a",
                "last_edited_time": "2026-10-01T10:00:00Z",
                "properties": {"title": {"type": "title", "title": [{"plain_text": "Selected Spec"}]}},
            },
            {
                "object": "page",
                "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "url": "https://notion.so/b",
                "last_edited_time": "2026-10-01T09:00:00Z",
                "properties": {"title": {"type": "title", "title": [{"plain_text": "Ignored Page"}]}},
            },
        ],
        "has_more": False,
    }
    direct_db_payload = {
        "object": "database",
        "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "url": "https://notion.so/c",
        "last_edited_time": "2026-10-02T10:00:00Z",
        "title": [{"plain_text": "Direct Runbook DB"}],
    }

    def fake_notion_req(method, url, **kwargs):
        if url.endswith("/search"):
            return _DummyResp(200, search_payload)
        if url.endswith("/databases/cccccccccccccccccccccccccccccccc"):
            return _DummyResp(200, direct_db_payload)
        if "/blocks/" in url:
            return _DummyResp(200, {"results": [], "has_more": False})
        if "/query" in url:
            return _DummyResp(200, {"results": [], "has_more": False})
        return _DummyResp(404, {})

    with patch.object(connector, "_request_with_retry", side_effect=fake_notion_req):
        listed = connector.list_accessible_resources(max_pages=1)
        assert [r["title"] for r in listed] == ["Selected Spec", "Ignored Page"]

        records, cursor = connector.sync(
            config={"targets": ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cccccccccccccccccccccccccccccccc"]}
        )

    titles = [r["title"] for r in records]
    assert titles == ["Notion: Selected Spec", "Notion: Direct Runbook DB"]
    assert "last_edited_time" in cursor


def test_api_discover_and_integration_resources_with_refresh_and_sync_isolation():
    ctx = _create_isolated_context()
    try:
        bad = client.post(
            "/api/v1/integrations/discover-resources",
            headers=ctx["headers"],
            json={"provider": "github", "token": ""},
        )
        assert bad.status_code == 400

        with patch.object(
            GitHubConnector,
            "list_repositories",
            return_value=[{"full_name": "acme/web-app", "private": False, "default_branch": "main", "html_url": "https://github.com/acme/web-app"}],
        ):
            disc = client.post(
                "/api/v1/integrations/discover-resources",
                headers=ctx["headers"],
                json={"provider": "github", "token": "ghp_live_mock"},
            )
            assert disc.status_code == 200
            body = disc.json()
            assert body["provider"] == "github"
            assert body["resources"][0]["value"] == "acme/web-app"

        db = SessionLocal()
        integ = Integration(
            project_id=ctx["project_id"],
            user_id=ctx["user_id"],
            provider="github",
            name="GitHub OAuth Test",
            auth_type="oauth",
            auth_status="verified",
            status="connected",
            credentials=encrypt_credentials({"access_token": "ghu_expired", "refresh_token": "ghr_valid"}),
            config={},
        )
        db.add(integ)
        db.commit()
        db.refresh(integ)
        integ_id = integ.id
        db.close()

        # Outsider is blocked with 403
        forbidden = client.get(f"/api/v1/integrations/{integ_id}/resources", headers=ctx["other_headers"])
        assert forbidden.status_code == 403

        def fake_list_repos(self, max_pages=3):
            if self.token == "ghu_expired":
                raise ConnectorError("GitHub rejected credentials while listing repositories (401): Bad credentials")
            return [{"full_name": "acme/refreshed-repo", "private": True, "default_branch": "main", "html_url": "https://github.com/acme/refreshed-repo"}]

        with (
            patch.object(GitHubConnector, "list_repositories", fake_list_repos),
            patch.object(
                GitHubConnector,
                "refresh_oauth_token",
                return_value={"access_token": "ghu_fresh", "token": "ghu_fresh", "refresh_token": "ghr_next"},
            ),
        ):
            res = client.get(f"/api/v1/integrations/{integ_id}/resources", headers=ctx["headers"])
            assert res.status_code == 200
            assert res.json()["resources"][0]["value"] == "acme/refreshed-repo"

        db = SessionLocal()
        updated_integ = db.query(Integration).filter(Integration.id == integ_id).first()
        creds_after = decrypt_credentials(updated_integ.credentials)
        db.close()
        assert creds_after["access_token"] == "ghu_fresh"

        # Verify sync isolates knowledge extraction errors and commits SourceRecords
        mock_records = [
            {
                "source_type": "github_pr",
                "external_id": "pr-1",
                "title": "PR #1: Add discovery endpoint",
                "author": "alice",
                "url": "https://github.com/acme/refreshed-repo/pull/1",
                "content": "Added resource listing endpoint for integration picker.",
                "sha256": "abc123",
            }
        ]
        with (
            patch.object(GitHubConnector, "sync", return_value=(mock_records, {"acme/refreshed-repo": "2026-10-01T00:00:00Z"})),
            patch("app.api.v1.integrations.extract_and_persist_project_knowledge", side_effect=RuntimeError("503 Gemini overloaded")),
        ):
            sync_res = client.post(f"/api/v1/integrations/{integ_id}/sync?extract_knowledge=true", headers=ctx["headers"])
            assert sync_res.status_code == 200
            sync_json = sync_res.json()
            assert sync_json["records_added"] == 1
            assert sync_json["details"]["extracted_knowledge"]["status"] == "scheduled"
    finally:
        _cleanup_context(ctx["org_id"], ctx["project_id"])


def test_github_oauth_callback_redirects_with_integration_id():
    ctx = _create_isolated_context()
    try:
        state = create_oauth_state_token({"sub": ctx["user_id"], "project_id": ctx["project_id"], "provider": "github"})
        with (
            patch.object(GitHubConnector, "exchange_oauth_code", return_value={"access_token": "ghu_oauth", "token": "ghu_oauth"}),
            patch.object(
                GitHubConnector,
                "check_connection",
                return_value={"status": "connected", "connected_account": "octocat", "scopes": ["repo"]},
            ),
        ):
            resp = client.get(
                f"/api/v1/integrations/oauth/github/callback?code=code123&state={state}",
                follow_redirects=False,
            )
        assert resp.status_code in (302, 307)
        loc = resp.headers["location"]
        assert "/integrations?connected=github&integration_id=" in loc
    finally:
        _cleanup_context(ctx["org_id"], ctx["project_id"])
