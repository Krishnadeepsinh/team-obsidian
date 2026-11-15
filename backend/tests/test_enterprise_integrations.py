import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.main import app
from app.core.database import SessionLocal, init_db
from app.core.security import create_access_token, encrypt_credentials
from app.models.integration import Integration, IntegrationProjectAccess
from app.models.workspace import User, Workspace, Project, Organization, ProjectMember
from app.services.connectors import LinearConnector
from app.services.connectors.base import ensure_valid_token


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
    # User B (Member of WS 1)
    user_b = User(
        id=str(uuid.uuid4()),
        email=f"member_{suffix}@test.io",
        name="Member User",
        role="developer",
        org_id=org.id,
        password_hash="test_pw_hash",
    )
    # User C (External Org)
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

    # Add ProjectMember records so get_user_accessible_project_ids sees them
    pm1 = ProjectMember(id=str(uuid.uuid4()), project_id=proj1.id, user_id=user_a.id, status="active")
    pm2 = ProjectMember(id=str(uuid.uuid4()), project_id=proj1.id, user_id=user_b.id, status="active")
    pm3 = ProjectMember(id=str(uuid.uuid4()), project_id=proj2.id, user_id=user_a.id, status="active")
    db_session.add_all([pm1, pm2, pm3])
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


def test_personal_token_isolation(test_setup, db_session):
    """Ensure personal developer tokens are NEVER leaked to other members of the same project."""
    client = TestClient(app)
    user_a = test_setup["user_a"]
    user_b = test_setup["user_b"]
    proj1 = test_setup["proj1"]

    token_a = create_access_token({"sub": user_a.id, "email": user_a.email, "role": user_a.role})
    token_b = create_access_token({"sub": user_b.id, "email": user_b.email, "role": user_b.role})

    # User A creates a personal integration
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


def test_organization_integration_multi_project_assignment(test_setup, db_session):
    """Ensure organization integrations can be assigned to multiple projects and unassigned cleanly."""
    client = TestClient(app)
    user_a = test_setup["user_a"]
    proj1 = test_setup["proj1"]
    proj2 = test_setup["proj2"]

    token_a = create_access_token({"sub": user_a.id, "email": user_a.email, "role": user_a.role})

    # Create an org integration assigned initially to proj1
    org_integ = Integration(
        id=str(uuid.uuid4()),
        project_id=proj1.id,
        workspace_id=test_setup["ws1"].id,
        user_id=user_a.id,
        authorized_by_user_id=user_a.id,
        authorized_by_email=user_a.email,
        connection_type="organization",
        external_org_id="ext_slack_team_1",
        external_org_name="Team Obsidian Enterprise",
        provider="slack",
        name="Enterprise Slack",
        connected_account="Team Obsidian (@bot)",
        status="connected",
        assigned_projects=[proj1.id],
        credentials=encrypt_credentials({"bot_token": "xoxb-mock-token"}),
    )
    db_session.add(org_integ)
    db_session.flush()
    db_session.add(IntegrationProjectAccess(id=str(uuid.uuid4()), integration_id=org_integ.id, project_id=proj1.id))
    db_session.commit()

    # Assign to proj2 as well
    assign_res = client.post(
        f"/api/v1/integrations/{org_integ.id}/assign",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"project_ids": [proj2.id]},
    )
    assert assign_res.status_code == 200
    assigned_list = assign_res.json()["assigned_projects"]
    assert proj1.id in assigned_list and proj2.id in assigned_list

    # Verify proj2 lists the org integration
    res_p2 = client.get(f"/api/v1/integrations?project_id={proj2.id}", headers={"Authorization": f"Bearer {token_a}"})
    assert res_p2.status_code == 200
    matched = next((i for i in res_p2.json() if i["id"] == org_integ.id), None)
    assert matched is not None
    assert matched["connection_type"] == "organization"
    assert matched["external_org_name"] == "Team Obsidian Enterprise"
    assert matched["authorized_by_email"] == user_a.email

    # Unassign from proj2
    unassign_res = client.post(
        f"/api/v1/integrations/{org_integ.id}/unassign",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"project_ids": [proj2.id]},
    )
    assert unassign_res.status_code == 200
    assert proj2.id not in unassign_res.json()["assigned_projects"]


def test_ensure_valid_token_auto_refresh(db_session):
    """Test automated token refresh logic when token expires within 5 minutes."""
    expiring_time = datetime.now(timezone.utc) + timedelta(minutes=2)
    integ = Integration(
        id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        provider="linear",
        name="Linear Sync Token Test",
        status="connected",
        token_expires_at=expiring_time,
        credentials=encrypt_credentials({
            "access_token": "lin_oauth_old_token",
            "refresh_token": "lin_refresh_token_xyz",
        }),
    )
    db_session.add(integ)
    db_session.commit()

    with patch.object(LinearConnector, "refresh_oauth_token") as mock_refresh:
        mock_refresh.return_value = {
            "access_token": "lin_oauth_new_token_123",
            "refresh_token": "lin_refresh_token_rotated",
            "expires_in": 7200,
        }

        active_token = ensure_valid_token(integ, db_session)
        assert active_token == "lin_oauth_new_token_123"
        assert mock_refresh.called

        db_session.refresh(integ)
        assert integ.status == "connected"
        assert integ.token_expires_at is not None
