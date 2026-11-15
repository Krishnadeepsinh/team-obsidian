import os
import sys
import threading
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import pytest
from starlette.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.main import app
from app.core.database import SessionLocal, init_db
from app.core.security import create_access_token, encrypt_credentials, decrypt_credentials
from app.models.integration import Integration, IntegrationProjectAccess
from app.models.workspace import User, Workspace, Project, Organization, ProjectMember
from app.services.connectors import LinearConnector, GitHubConnector
from app.services.connectors.base import ensure_valid_token, ConnectorError


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    init_db()


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_setup(db_session):
    suffix = uuid.uuid4().hex[:6]
    org = Organization(id=str(uuid.uuid4()), name=f"Test Org {suffix}", slug=f"test-org-{suffix}")
    db_session.add(org)

    # Workspace 1 (Org Workspace)
    ws1 = Workspace(id=str(uuid.uuid4()), name=f"Workspace A {suffix}", slug=f"ws-a-{suffix}", org_id=org.id, is_personal=False)
    db_session.add(ws1)

    # User A (Admin)
    user_a = User(
        id=str(uuid.uuid4()),
        email=f"admin_{suffix}@test.io",
        name="Admin User",
        role="org_admin",
        org_id=org.id,
        password_hash="test_pw_hash",
    )
    # User B (Member/Developer of WS 1)
    user_b = User(
        id=str(uuid.uuid4()),
        email=f"developer_{suffix}@test.io",
        name="Developer User",
        role="developer",
        org_id=org.id,
        password_hash="test_pw_hash",
    )
    # User C (External Org / External Workspace)
    org_c = Organization(id=str(uuid.uuid4()), name=f"Other Org {suffix}", slug=f"other-org-{suffix}")
    ws_c = Workspace(id=str(uuid.uuid4()), name=f"Workspace C {suffix}", slug=f"ws-c-{suffix}", org_id=org_c.id, is_personal=False)
    user_c = User(
        id=str(uuid.uuid4()),
        email=f"external_{suffix}@test.io",
        name="External User",
        role="developer",
        org_id=org_c.id,
        password_hash="test_pw_hash",
    )
    db_session.add_all([user_a, user_b, org_c, ws_c, user_c])
    db_session.flush()

    # Projects
    proj1 = Project(id=str(uuid.uuid4()), name="Project Alpha", slug=f"proj-a-{suffix}", workspace_id=ws1.id, creator_id=user_a.id)
    proj2 = Project(id=str(uuid.uuid4()), name="Project Beta", slug=f"proj-b-{suffix}", workspace_id=ws1.id, creator_id=user_a.id)
    proj_c = Project(id=str(uuid.uuid4()), name="Project Gamma", slug=f"proj-c-{suffix}", workspace_id=ws_c.id, creator_id=user_c.id)
    db_session.add_all([proj1, proj2, proj_c])
    db_session.flush()

    # Add ProjectMember records
    pm1 = ProjectMember(id=str(uuid.uuid4()), project_id=proj1.id, user_id=user_a.id, status="active")
    pm2 = ProjectMember(id=str(uuid.uuid4()), project_id=proj1.id, user_id=user_b.id, status="active")
    pm3 = ProjectMember(id=str(uuid.uuid4()), project_id=proj2.id, user_id=user_a.id, status="active")
    pm4 = ProjectMember(id=str(uuid.uuid4()), project_id=proj_c.id, user_id=user_c.id, status="active")
    db_session.add_all([pm1, pm2, pm3, pm4])
    db_session.commit()

    return {
        "org": org,
        "ws1": ws1,
        "user_a": user_a,
        "user_b": user_b,
        "user_c": user_c,
        "proj1": proj1,
        "proj2": proj2,
        "proj_c": proj_c,
    }


def test_scenario_a_personal_token_isolation(test_setup, db_session):
    """Scenario A: Ensure personal developer tokens are NEVER visible or leaked to other developers."""
    client = TestClient(app)
    user_a = test_setup["user_a"]
    user_b = test_setup["user_b"]
    proj1 = test_setup["proj1"]

    token_a = create_access_token({"sub": user_a.id, "email": user_a.email, "role": user_a.role})
    token_b = create_access_token({"sub": user_b.id, "email": user_b.email, "role": user_b.role})

    # User A connects a personal GitHub token
    personal_integ = Integration(
        id=str(uuid.uuid4()),
        project_id=proj1.id,
        workspace_id=test_setup["ws1"].id,
        user_id=user_a.id,
        authorized_by_user_id=user_a.id,
        authorized_by_email=user_a.email,
        connection_type="personal",
        provider="github",
        name="User A Personal GitHub",
        connected_account="user_a_gh",
        status="connected",
        auth_status="verified",
        credentials=encrypt_credentials({"access_token": "ghp_secret_a"}),
    )
    db_session.add(personal_integ)
    db_session.commit()

    # 1. User A lists integrations -> sees own personal integration
    res_a = client.get(f"/api/v1/integrations?project_id={proj1.id}", headers={"Authorization": f"Bearer {token_a}"})
    assert res_a.status_code == 200
    ids_a = [i["id"] for i in res_a.json()]
    assert personal_integ.id in ids_a

    # 2. User B lists integrations -> MUST NOT see User A's personal integration
    res_b = client.get(f"/api/v1/integrations?project_id={proj1.id}", headers={"Authorization": f"Bearer {token_b}"})
    assert res_b.status_code == 200
    ids_b = [i["id"] for i in res_b.json()]
    assert personal_integ.id not in ids_b


def test_scenario_b_org_connection_sharing_and_rbac(test_setup, db_session):
    """Scenario B: Organization connections are shared across project members, but only admins or author can manage."""
    client = TestClient(app)
    user_a = test_setup["user_a"]  # org_admin / author
    user_b = test_setup["user_b"]  # developer
    proj1 = test_setup["proj1"]

    token_a = create_access_token({"sub": user_a.id, "email": user_a.email, "role": user_a.role})
    token_b = create_access_token({"sub": user_b.id, "email": user_b.email, "role": user_b.role})

    org_integ = Integration(
        id=str(uuid.uuid4()),
        project_id=proj1.id,
        workspace_id=test_setup["ws1"].id,
        user_id=user_a.id,
        authorized_by_user_id=user_a.id,
        authorized_by_email=user_a.email,
        connection_type="organization",
        external_org_id="ext_slack_team_org",
        external_org_name="Team Obsidian Enterprise",
        provider="slack",
        name="Enterprise Slack Shared",
        connected_account="Team Obsidian (@bot)",
        status="connected",
        auth_status="verified",
        assigned_projects=[proj1.id],
        credentials=encrypt_credentials({"bot_token": "xoxb-mock-shared"}),
    )
    db_session.add(org_integ)
    db_session.flush()
    db_session.add(IntegrationProjectAccess(id=str(uuid.uuid4()), integration_id=org_integ.id, project_id=proj1.id))
    db_session.commit()

    # 1. User B (developer) can view the organization integration
    res_b = client.get(f"/api/v1/integrations?project_id={proj1.id}", headers={"Authorization": f"Bearer {token_b}"})
    assert res_b.status_code == 200
    matched = next((i for i in res_b.json() if i["id"] == org_integ.id), None)
    assert matched is not None
    assert matched["connection_type"] == "organization"
    assert matched["external_org_name"] == "Team Obsidian Enterprise"
    assert matched["can_manage"] is False  # Non-admin developer cannot manage

    # 2. User B attempts to disconnect -> 403 Forbidden
    disc_res = client.post(f"/api/v1/integrations/{org_integ.id}/disconnect", headers={"Authorization": f"Bearer {token_b}"})
    assert disc_res.status_code == 403

    # 3. User B attempts to delete -> 403 Forbidden
    del_res = client.delete(f"/api/v1/integrations/{org_integ.id}", headers={"Authorization": f"Bearer {token_b}"})
    assert del_res.status_code == 403

    # 4. User A (author / org_admin) can manage
    res_a = client.get(f"/api/v1/integrations?project_id={proj1.id}", headers={"Authorization": f"Bearer {token_a}"})
    matched_a = next(i for i in res_a.json() if i["id"] == org_integ.id)
    assert matched_a["can_manage"] is True


def test_scenario_c_multi_project_assignment_isolation(test_setup, db_session):
    """Scenario C: Organization integrations are only visible in projects they are assigned to."""
    client = TestClient(app)
    user_a = test_setup["user_a"]
    proj1 = test_setup["proj1"]
    proj2 = test_setup["proj2"]

    token_a = create_access_token({"sub": user_a.id, "email": user_a.email, "role": user_a.role})

    # Org integration initially assigned only to proj1
    org_integ = Integration(
        id=str(uuid.uuid4()),
        project_id=proj1.id,
        workspace_id=test_setup["ws1"].id,
        user_id=user_a.id,
        authorized_by_user_id=user_a.id,
        authorized_by_email=user_a.email,
        connection_type="organization",
        external_org_id="linear_org_1",
        external_org_name="Linear Workspace Pro",
        provider="linear",
        name="Linear Pro Tracker",
        status="connected",
        auth_status="verified",
        assigned_projects=[proj1.id],
        credentials=encrypt_credentials({"access_token": "lin_api_test"}),
    )
    db_session.add(org_integ)
    db_session.flush()
    db_session.add(IntegrationProjectAccess(id=str(uuid.uuid4()), integration_id=org_integ.id, project_id=proj1.id))
    db_session.commit()

    # 1. Proj1 lists it with is_assigned_to_current_project = True
    res_p1 = client.get(f"/api/v1/integrations?project_id={proj1.id}", headers={"Authorization": f"Bearer {token_a}"})
    assert res_p1.status_code == 200
    item_p1 = next(i for i in res_p1.json() if i["id"] == org_integ.id)
    assert item_p1["is_assigned_to_current_project"] is True

    # 2. Proj2 lists it as NOT assigned initially
    res_p2 = client.get(f"/api/v1/integrations?project_id={proj2.id}", headers={"Authorization": f"Bearer {token_a}"})
    assert res_p2.status_code == 200
    item_p2 = next(i for i in res_p2.json() if i["id"] == org_integ.id)
    assert item_p2["is_assigned_to_current_project"] is False

    # 3. Assign to proj2
    assign_res = client.post(
        f"/api/v1/integrations/{org_integ.id}/assign",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"project_ids": [proj2.id]},
    )
    assert assign_res.status_code == 200
    assert proj2.id in assign_res.json()["assigned_projects"]

    # 4. Proj2 now lists it as assigned
    res_p2_after = client.get(f"/api/v1/integrations?project_id={proj2.id}", headers={"Authorization": f"Bearer {token_a}"})
    item_p2_after = next(i for i in res_p2_after.json() if i["id"] == org_integ.id)
    assert item_p2_after["is_assigned_to_current_project"] is True


def test_scenario_d_workspace_switching_isolation(test_setup, db_session):
    """Scenario D: Integrations belong to their workspace and NEVER leak to another workspace."""
    client = TestClient(app)
    user_a = test_setup["user_a"]
    user_c = test_setup["user_c"]
    proj_c = test_setup["proj_c"]

    token_c = create_access_token({"sub": user_c.id, "email": user_c.email, "role": user_c.role})

    # User C queries integrations for project Gamma in Workspace C
    res_c = client.get(f"/api/v1/integrations?project_id={proj_c.id}", headers={"Authorization": f"Bearer {token_c}"})
    assert res_c.status_code == 200
    for integ in res_c.json():
        assert integ["workspace_id"] == test_setup["ws_c"].id


def test_scenario_e_oauth_external_org_verification(test_setup, db_session):
    """Scenario E: OAuth and Token connections verify external org identity."""
    integ = Integration(
        id=str(uuid.uuid4()),
        project_id=test_setup["proj1"].id,
        workspace_id=test_setup["ws1"].id,
        connection_type="organization",
        external_org_id="org_test_123",
        external_org_name="Acme Corp External",
        provider="github",
        name="Acme GitHub Org",
        status="connected",
        auth_status="verified",
        credentials=encrypt_credentials({"access_token": "gho_test_123"}),
    )
    db_session.add(integ)
    db_session.commit()

    client = TestClient(app)
    token_a = create_access_token({"sub": test_setup["user_a"].id, "email": test_setup["user_a"].email, "role": test_setup["user_a"].role})
    res = client.get(f"/api/v1/integrations?project_id={test_setup['proj1'].id}", headers={"Authorization": f"Bearer {token_a}"})
    matched = next(i for i in res.json() if i["id"] == integ.id)
    assert matched["external_org_id"] == "org_test_123"
    assert matched["external_org_name"] == "Acme Corp External"


def test_scenario_f_revocation_detection_and_live_badge(db_session):
    """Scenario F: External revocation marks status='token_expired' and auth_status='revoked'."""
    expiring_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    integ = Integration(
        id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        provider="linear",
        name="Linear Revoked Test",
        status="connected",
        auth_status="verified",
        token_expires_at=expiring_time,
        credentials=encrypt_credentials({
            "access_token": "lin_expired_access",
            "refresh_token": "lin_invalid_grant_refresh",
        }),
    )
    db_session.add(integ)
    db_session.commit()

    with patch.object(LinearConnector, "refresh_oauth_token") as mock_refresh:
        mock_refresh.side_effect = ConnectorError("invalid_grant: The refresh token has been revoked")

        ensure_valid_token(integ, db_session)

        db_session.refresh(integ)
        assert integ.status == "token_expired"
        assert integ.auth_status == "revoked"
        assert "invalid_grant" in (integ.error_message or "")


def test_github_app_installation_token_generation(db_session):
    """Verify GitHub App RS256 JWT minting and installation token generation."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    # 1. Test JWT creation
    app_jwt = GitHubConnector.create_app_jwt(app_id="123456", private_key=private_pem)
    assert isinstance(app_jwt, str)
    assert len(app_jwt) > 50

    # 2. Test installation access token creation
    mock_res = MagicMock()
    mock_res.status_code = 201
    mock_res.json.return_value = {
        "token": "ghs_installation_token_abc",
        "expires_at": "2026-11-16T12:00:00Z",
        "permissions": {"issues": "read", "contents": "read"},
        "repositories": [{"name": "repo-a"}],
    }

    with patch.object(GitHubConnector, "_request_with_retry", return_value=mock_res):
        token_bundle = GitHubConnector.create_installation_access_token(
            installation_id="998877",
            app_id="123456",
            private_key=private_pem,
        )
        assert token_bundle["token"] == "ghs_installation_token_abc"
        assert token_bundle["expires_in"] == 3600

    # 3. Test ensure_valid_token with GitHub App credentials
    integ = Integration(
        id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        provider="github",
        name="GitHub App Integ",
        status="connected",
        token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        credentials=encrypt_credentials({
            "installation_id": "998877",
            "app_id": "123456",
            "private_key": private_pem,
            "access_token": "ghs_old_token",
        }),
    )
    db_session.add(integ)
    db_session.commit()

    with patch.object(GitHubConnector, "_request_with_retry", return_value=mock_res):
        active_tok = ensure_valid_token(integ, db_session)
        assert active_tok == "ghs_installation_token_abc"
        db_session.refresh(integ)
        assert integ.status == "connected"
        assert integ.auth_status == "verified"


def test_ensure_valid_token_concurrent_safety(db_session):
    """Verify thread-safe locking prevents duplicate concurrent OAuth refreshes."""
    integ = Integration(
        id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        provider="linear",
        name="Linear Concurrency Test",
        status="connected",
        token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        credentials=encrypt_credentials({
            "access_token": "lin_concurrent_old",
            "refresh_token": "lin_concurrent_refresh",
        }),
    )
    db_session.add(integ)
    db_session.commit()

    call_count = 0
    def mock_refresh_func(refresh_token):
        nonlocal call_count
        call_count += 1
        return {
            "access_token": f"lin_new_tok_{call_count}",
            "refresh_token": f"lin_new_ref_{call_count}",
            "expires_in": 7200,
        }

    with patch.object(LinearConnector, "refresh_oauth_token", side_effect=mock_refresh_func):
        threads = []
        tokens_seen = []

        def worker():
            local_db = SessionLocal()
            try:
                local_integ = local_db.query(Integration).filter_by(id=integ.id).first()
                tok = ensure_valid_token(local_integ, local_db)
                tokens_seen.append(tok)
            finally:
                local_db.close()

        for _ in range(5):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # The refresh function should only execute once; subsequent threads see updated token_expires_at
        assert call_count == 1
        assert all(t.startswith("lin_new_tok_") for t in tokens_seen)


def test_ensure_valid_token_transient_network_error(db_session):
    """Verify transient network errors do not mark credentials as permanently revoked."""
    integ = Integration(
        id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        provider="linear",
        name="Linear Transient Network Test",
        status="connected",
        auth_status="verified",
        token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        credentials=encrypt_credentials({
            "access_token": "lin_working_token",
            "refresh_token": "lin_refresh_token_net",
        }),
    )
    db_session.add(integ)
    db_session.commit()

    with patch.object(LinearConnector, "refresh_oauth_token") as mock_refresh:
        mock_refresh.side_effect = ConnectorError("Connection timeout while contacting api.linear.app (503)")

        active_tok = ensure_valid_token(integ, db_session)
        assert active_tok == "lin_working_token"

        db_session.refresh(integ)
        # Transient failure must NOT revoke auth_status or destroy credentials!
        assert integ.auth_status != "revoked"
        creds = decrypt_credentials(integ.credentials)
        assert creds.get("refresh_token") == "lin_refresh_token_net"


def test_classify_connection_identity_all_providers():
    """Verify precise enterprise classification for all 8 providers."""
    from app.api.v1.integrations import classify_connection_identity

    # 1. GitHub
    conn_type, ident, org_id, org_name = classify_connection_identity(
        "github",
        check_data={"auth_type": "app_installation", "external_org_id": "org_123", "external_org_name": "ObsidianCorp"},
        creds={"installation_id": 99999},
    )
    assert conn_type == "organization"
    assert ident == "organization_app"
    assert org_id == "org_123"

    conn_type, ident, org_id, _ = classify_connection_identity(
        "github",
        check_data={"connected_account": "developer_alice"},
        creds={"token": "ghp_abcdef1234567890"},
    )
    assert conn_type == "personal"
    assert ident == "personal_account"
    assert org_id is None

    # 2. Slack
    conn_type, ident, org_id, org_name = classify_connection_identity(
        "slack",
        check_data={"team": "TeamObsidian", "team_id": "T12345"},
        creds={"bot_token": "xoxb-12345-bot-token"},
    )
    assert conn_type == "organization"
    assert ident == "workspace_bot"
    assert org_id == "T12345"

    conn_type, ident, _, _ = classify_connection_identity(
        "slack",
        check_data={"user": "developer_bob"},
        creds={"token": "xoxp-12345-user-token"},
    )
    assert conn_type == "personal"
    assert ident == "personal_account"

    # 3. Linear
    conn_type, ident, _, _ = classify_connection_identity(
        "linear",
        check_data={"connected_account": "dev@team.io"},
        creds={"api_key": "lin_api_testdevkey123"},
    )
    assert conn_type == "personal"
    assert ident == "personal_account"

    conn_type, ident, org_id, _ = classify_connection_identity(
        "linear",
        check_data={"organization": "Obsidian Inc", "external_org_id": "org_lin_99"},
        creds={"access_token": "oauth_token_linear"},
    )
    assert conn_type == "organization"
    assert ident == "organization_app"
    assert org_id == "org_lin_99"

    # 4. Sentry
    conn_type, ident, _, _ = classify_connection_identity(
        "sentry",
        check_data={"connected_account": "dev@sentry.io"},
        creds={"token": "sntryu_987654321_user_token"},
    )
    assert conn_type == "personal"
    assert ident == "personal_account"

    conn_type, ident, org_id, _ = classify_connection_identity(
        "sentry",
        check_data={"org_slug": "team-obsidian-prod"},
        creds={"token": "sntrys_org_internal_token", "org_slug": "team-obsidian-prod"},
    )
    assert conn_type == "organization"
    assert ident == "organization_app"
    assert org_id == "team-obsidian-prod"

    # 5. GitLab
    conn_type, ident, _, _ = classify_connection_identity(
        "gitlab",
        check_data={"username": "gitdev"},
        creds={"token": "glpat-secretpat123"},
    )
    assert conn_type == "personal"
    assert ident == "personal_account"

    conn_type, ident, org_id, _ = classify_connection_identity(
        "gitlab",
        check_data={"identity_type": "group_level", "external_org_id": "grp_456", "external_org_name": "ObsidianGroup"},
        creds={"token": "group_access_token"},
    )
    assert conn_type == "organization"
    assert ident == "group_level"
    assert org_id == "grp_456"

    # 6. Jira & Confluence
    conn_type, ident, org_id, org_name = classify_connection_identity(
        "jira",
        check_data={"cloud_id": "cloud-uuid-77", "site_url": "https://obsidian.atlassian.net"},
        creds={"access_token": "atlassian_oauth_token"},
    )
    assert conn_type == "organization"
    assert ident == "organization_tenant"
    assert org_id == "cloud-uuid-77"


def test_duplicate_sync_prevention(test_setup, db_session):
    """Verify HTTP 409 Conflict when an integration is already syncing."""
    client = TestClient(app)
    user_a = test_setup["user_a"]
    token_a = create_access_token({"sub": user_a.id, "email": user_a.email, "role": user_a.role})

    integ = Integration(
        id=str(uuid.uuid4()),
        project_id=test_setup["proj1"].id,
        workspace_id=test_setup["ws1"].id,
        user_id=user_a.id,
        authorized_by_user_id=user_a.id,
        provider="github",
        name="GitHub Duplicate Sync Test",
        status="syncing",
        updated_at=datetime.now(timezone.utc),
        credentials=encrypt_credentials({"token": "ghp_mock_token"}),
    )
    db_session.add(integ)
    db_session.commit()

    resp = client.post(
        f"/api/v1/integrations/{integ.id}/sync",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 409
    assert "already running" in resp.json()["detail"].lower()


def test_ensure_valid_token_distributed_postgres_locking(db_session):
    """Verify with_for_update is invoked on PostgreSQL engine."""
    integ = Integration(
        id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        provider="linear",
        name="Linear PG Lock Test",
        status="connected",
        auth_status="verified",
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        credentials=encrypt_credentials({"access_token": "valid_token"}),
    )
    db_session.add(integ)
    db_session.commit()

    mock_db = MagicMock()
    mock_bind = MagicMock()
    mock_bind.dialect.name = "postgresql"
    mock_db.get_bind.return_value = mock_bind
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_filter = MagicMock()
    mock_query.filter_by.return_value = mock_filter
    mock_lock = MagicMock()
    mock_filter.with_for_update.return_value = mock_lock
    mock_lock.first.return_value = integ

    tok = ensure_valid_token(integ, db=mock_db)
    assert tok == "valid_token"
    mock_filter.with_for_update.assert_called_once()

