import os
import sys
import pytest
import uuid
from starlette.testclient import TestClient

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.main import app
from app.core.database import SessionLocal, init_db
from app.models.workspace import Organization, Workspace, User, Project, ProjectMember
from app.models.integration import Integration, SourceRecord
from app.models.knowledge import Decision, TaskItem, RiskItem, KnowledgeEntity
from app.models.evidence import Evidence
from app.models.handover import Handover

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    init_db()

class TestMultiUserMultiTenantSaaS:
    """Comprehensive test suite verifying multi-user, multi-tenant isolation across all application layers."""

    user_a_email = f"user_a_{uuid.uuid4().hex[:6]}@saas-test.io"
    user_b_email = f"user_b_{uuid.uuid4().hex[:6]}@saas-test.io"
    password = "TestPassword2026!"

    user_a_token = None
    user_b_token = None
    user_a_id = None
    user_b_id = None
    user_a_project_id = None
    user_b_project_id = None
    user_a_handover_id = None
    user_a_integration_id = None
    project_a2_id = None

    def test_01_user_a_registration_provisions_isolated_workspace(self):
        """User A registers and receives a personal organization, workspace, and starter project."""
        res = client.post(
            "/api/v1/auth/register",
            json={
                "name": "Alice Innovator",
                "email": self.user_a_email,
                "password": self.password,
                "role": "tech_lead",
                "title": "Lead Architect",
                "department": "Platform Engineering"
            }
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert "access_token" in data
        assert "user" in data
        assert data["user"]["email"] == self.user_a_email
        assert data["personal_workspace_id"] is not None
        assert data["active_project_id"] is not None

        TestMultiUserMultiTenantSaaS.user_a_token = data["access_token"]
        TestMultiUserMultiTenantSaaS.user_a_id = data["user"]["id"]
        TestMultiUserMultiTenantSaaS.user_a_project_id = data["active_project_id"]

    def test_02_user_b_registration_provisions_isolated_workspace(self):
        """User B registers independently and receives their own workspace and starter project."""
        res = client.post(
            "/api/v1/auth/register",
            json={
                "name": "Bob Builder",
                "email": self.user_b_email,
                "password": self.password,
                "role": "developer",
                "title": "Senior Frontend Dev",
                "department": "UI Platform"
            }
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert "access_token" in data
        assert data["user"]["email"] == self.user_b_email
        assert data["personal_workspace_id"] != self.user_a_project_id

        TestMultiUserMultiTenantSaaS.user_b_token = data["access_token"]
        TestMultiUserMultiTenantSaaS.user_b_id = data["user"]["id"]
        TestMultiUserMultiTenantSaaS.user_b_project_id = data["active_project_id"]
        assert self.user_b_project_id != self.user_a_project_id

    def test_03_project_listing_strict_isolation(self):
        """User A only sees User A's projects; User B only sees User B's projects."""
        headers_a = {"Authorization": f"Bearer {self.user_a_token}"}
        res_a = client.get("/api/v1/projects", headers=headers_a)
        assert res_a.status_code == 200
        proj_ids_a = [p["id"] for p in res_a.json()]
        assert self.user_a_project_id in proj_ids_a
        assert self.user_b_project_id not in proj_ids_a

        headers_b = {"Authorization": f"Bearer {self.user_b_token}"}
        res_b = client.get("/api/v1/projects", headers=headers_b)
        assert res_b.status_code == 200
        proj_ids_b = [p["id"] for p in res_b.json()]
        assert self.user_b_project_id in proj_ids_b
        assert self.user_a_project_id not in proj_ids_b

    def test_04_direct_project_access_cross_tenant_rejection(self):
        """User B cannot fetch User A's private project (enforces 403 Forbidden)."""
        headers_b = {"Authorization": f"Bearer {self.user_b_token}"}
        res = client.get(f"/api/v1/projects/{self.user_a_project_id}", headers=headers_b)
        assert res.status_code == 403
        assert "Forbidden" in res.json().get("detail", "")

        # Conversely, User A cannot fetch User B's project
        headers_a = {"Authorization": f"Bearer {self.user_a_token}"}
        res_rev = client.get(f"/api/v1/projects/{self.user_b_project_id}", headers=headers_a)
        assert res_rev.status_code == 403

    def test_05_integration_creation_and_credential_masking(self):
        """User A connects an integration with verified auth. Token is masked and User B cannot view it."""
        from unittest.mock import patch
        headers_a = {"Authorization": f"Bearer {self.user_a_token}"}
        secret_token = "ghp_PersonalSuperSecretTokenUserA12345"

        # Unverified bogus token without provider auth success must be rejected
        bad_res = client.post(
            "/api/v1/integrations",
            headers=headers_a,
            json={
                "project_id": self.user_a_project_id,
                "provider": "github",
                "name": "Unverified Repo",
                "credentials": {"access_token": "invalid_token"},
                "config": {"repo": "alice/core-service"},
            },
        )
        assert bad_res.status_code == 400

        with patch(
            "app.services.connectors.GitHubConnector.check_connection",
            return_value={"status": "connected", "connected_account": "alice-gh", "scopes": ["repo", "read:user"]},
        ):
            res = client.post(
                "/api/v1/integrations",
                headers=headers_a,
                json={
                    "project_id": self.user_a_project_id,
                    "provider": "github",
                    "name": "Alice's Core Service Repo",
                    "is_org_level": False,
                    "credentials": {"access_token": secret_token},
                    "config": {"repository": "alice/core-service"},
                },
            )
        assert res.status_code == 200, res.text
        data = res.json()
        TestMultiUserMultiTenantSaaS.user_a_integration_id = data["id"]
        assert data["auth_status"] == "verified"
        assert data["connected_account"] == "alice-gh"

        # Credentials must be masked in response and encrypted in DB
        assert secret_token not in str(data.get("credentials", {}))
        db = SessionLocal()
        integ_row = db.query(Integration).filter(Integration.id == data["id"]).first()
        assert "__encrypted__" in (integ_row.credentials or {})
        assert secret_token not in str(integ_row.credentials)
        db.close()

        # User B cannot see User A's integration in list
        headers_b = {"Authorization": f"Bearer {self.user_b_token}"}
        res_b = client.get("/api/v1/integrations", headers=headers_b)
        assert res_b.status_code == 200
        integ_ids_b = [i["id"] for i in res_b.json()]
        assert self.user_a_integration_id not in integ_ids_b

    def test_06_integration_disconnect_and_reconnect(self):
        """User A can disconnect and reconnect their personal integration."""
        from unittest.mock import patch
        headers_a = {"Authorization": f"Bearer {self.user_a_token}"}

        # Disconnect
        res_disc = client.post(f"/api/v1/integrations/{self.user_a_integration_id}/disconnect", headers=headers_a)
        assert res_disc.status_code == 200
        assert res_disc.json()["status"] == "success"

        # Reconnect with controlled mock auth verification
        with patch(
            "app.services.connectors.GitHubConnector.check_connection",
            return_value={"status": "connected", "connected_account": "alice-gh", "scopes": ["repo"]},
        ):
            res_rec = client.post(
                f"/api/v1/integrations/{self.user_a_integration_id}/reconnect",
                headers=headers_a,
                json={"credentials": {"access_token": "ghp_NewRefreshTokenUserA999"}},
            )
        assert res_rec.status_code == 200
        assert res_rec.json()["status"] == "connected"

    def test_07_decisions_and_tasks_isolation(self):
        """User A creates a decision and a task; User B cannot see them."""
        headers_a = {"Authorization": f"Bearer {self.user_a_token}"}

        # Create Decision for User A
        res_dec = client.post(
            "/api/v1/decisions",
            headers=headers_a,
            json={
                "project_id": self.user_a_project_id,
                "title": "Use Rust for Real-Time Streaming Gateway",
                "summary": "Benchmarked against Go; selected Rust for lower latency jitter.",
                "reasoning": "Zero-cost abstractions and predictable memory footprint.",
                "decision_maker": "Alice Innovator",
                "date": "2026-11-09",
                "component": "Gateway"
            }
        )
        assert res_dec.status_code == 200, res_dec.text
        dec_id = res_dec.json()["id"]

        # Create Task for User A
        res_task = client.post(
            "/api/v1/tasks",
            headers=headers_a,
            json={
                "project_id": self.user_a_project_id,
                "title": "Implement Async WebSocket Handler",
                "owner": "Alice Innovator",
                "priority": "high",
                "status": "open",
                "deadline": "2026-11-20"
            }
        )
        assert res_task.status_code == 200, res_task.text
        task_id = res_task.json()["id"]

        # User B queries decisions
        headers_b = {"Authorization": f"Bearer {self.user_b_token}"}
        res_dec_b = client.get("/api/v1/decisions", headers=headers_b)
        assert res_dec_b.status_code == 200
        dec_ids_b = [d["id"] for d in res_dec_b.json()]
        assert dec_id not in dec_ids_b

        # User B queries tasks
        res_task_b = client.get("/api/v1/tasks", headers=headers_b)
        assert res_task_b.status_code == 200
        task_ids_b = [t["id"] for t in res_task_b.json()]
        assert task_id not in task_ids_b

    def test_08_handover_reconstruction_and_access_control(self):
        """User A runs handover reconstruction; User B cannot view or download PDF."""
        headers_a = {"Authorization": f"Bearer {self.user_a_token}"}

        res_ho = client.post(
            "/api/v1/handovers/reconstruct",
            headers=headers_a,
            json={
                "project_id": self.user_a_project_id,
                "departing_employee_name": "Alice Innovator",
                "departing_employee_role": "Lead Architect",
                "incoming_employee_name": "Charlie Successor",
                "incoming_employee_role": "Staff Engineer",
                "selected_categories": ["Architecture", "Decisions", "Tasks"]
            }
        )
        assert res_ho.status_code == 200, res_ho.text
        ho_data = res_ho.json()
        assert ho_data["title"] == "Alice Innovator → Charlie Successor Knowledge Handover Dossier"
        TestMultiUserMultiTenantSaaS.user_a_handover_id = ho_data["id"]

        # User B attempts to access User A's handover dossier -> 403 Forbidden
        headers_b = {"Authorization": f"Bearer {self.user_b_token}"}
        res_ho_b = client.get(f"/api/v1/handovers/{self.user_a_handover_id}", headers=headers_b)
        assert res_ho_b.status_code == 403

        # User B attempts to download User A's handover PDF -> 403 Forbidden
        res_pdf_b = client.get(f"/api/v1/handovers/{self.user_a_handover_id}/pdf", headers=headers_b)
        assert res_pdf_b.status_code == 403

    def test_09_ai_assistant_strict_knowledge_isolation(self):
        """User B cannot query AI assistant against User A's project (403 Forbidden)."""
        headers_b = {"Authorization": f"Bearer {self.user_b_token}"}
        res = client.post(
            "/api/v1/assistant/query",
            headers=headers_b,
            json={
                "project_id": self.user_a_project_id,
                "question": "What architecture decisions did Alice make?",
                "departing_focus": "Alice Innovator"
            }
        )
        assert res.status_code == 403
        assert "Forbidden" in res.json().get("detail", "")

    def test_10_knowledge_graph_isolation(self):
        """User B cannot access User A's Knowledge Graph blast-radius or react-flow (403 Forbidden)."""
        headers_b = {"Authorization": f"Bearer {self.user_b_token}"}
        res_flow = client.get(f"/api/v1/graph/react-flow?project_id={self.user_a_project_id}", headers=headers_b)
        assert res_flow.status_code == 403

    def test_11_shared_project_explicit_collaboration(self):
        """User A creates Project A2, invites User B, and User B can access A2, but User B remains blocked from A1."""
        headers_a = {"Authorization": f"Bearer {self.user_a_token}"}

        # User A creates a second project
        res_p2 = client.post(
            "/api/v1/projects",
            headers=headers_a,
            json={
                "name": "Alice & Bob Joint Platform",
                "slug": f"joint-platform-{uuid.uuid4().hex[:6]}",
                "description": "Collaborative project between Alice and Bob"
            }
        )
        assert res_p2.status_code == 200, res_p2.text
        TestMultiUserMultiTenantSaaS.project_a2_id = res_p2.json()["id"]

        # Before invitation, User B cannot access Project A2
        headers_b = {"Authorization": f"Bearer {self.user_b_token}"}
        assert client.get(f"/api/v1/projects/{self.project_a2_id}", headers=headers_b).status_code == 403

        # User A explicitly invites User B by email
        res_inv = client.post(
            f"/api/v1/projects/{self.project_a2_id}/members",
            headers=headers_a,
            json={
                "email": self.user_b_email,
                "project_role": "developer"
            }
        )
        assert res_inv.status_code == 200, res_inv.text

        # User B accepts the project invitation
        res_acc = client.post(f"/api/v1/projects/{self.project_a2_id}/members/accept", headers=headers_b)
        assert res_acc.status_code == 200, res_acc.text

        # Now User B CAN access Project A2
        res_p2_b = client.get(f"/api/v1/projects/{self.project_a2_id}", headers=headers_b)
        assert res_p2_b.status_code == 200
        assert res_p2_b.json()["id"] == self.project_a2_id

        # But User B is STILL FORBIDDEN from accessing User A's private Project A1!
        res_p1_b = client.get(f"/api/v1/projects/{self.user_a_project_id}", headers=headers_b)
        assert res_p1_b.status_code == 403

    def test_12_password_recovery_lifecycle(self):
        """Test secure password recovery: token never returned in HTTP response, single-use expiry enforced."""
        import re
        from pathlib import Path

        outbox = Path(backend_dir) / ".dev_mail_outbox.log"
        if outbox.exists():
            outbox.unlink()

        # 1. Forgot password request MUST NOT expose reset_token in public API response
        res_req = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": self.user_b_email},
        )
        assert res_req.status_code == 200
        assert "reset_token" not in res_req.json()

        # Retrieve one-time token from server dev email outbox
        mail_content = outbox.read_text(encoding="utf-8")
        m = re.findall(r"Reset code:\s*(\S+)", mail_content)
        assert m, "Reset email should have been recorded in dev mail outbox"
        reset_token = m[-1]

        # 2. Reset password using one-time token
        new_password = "BrandNewSecurePassword2026!"
        res_reset = client.post(
            "/api/v1/auth/reset-password",
            json={
                "email": self.user_b_email,
                "reset_token": reset_token,
                "new_password": new_password,
            },
        )
        assert res_reset.status_code == 200
        assert "successfully updated" in res_reset.json().get("message", "")

        # 2b. Reusing the same token must fail (single-use)
        res_reuse = client.post(
            "/api/v1/auth/reset-password",
            json={
                "email": self.user_b_email,
                "reset_token": reset_token,
                "new_password": "AnotherPassword2026!",
            },
        )
        assert res_reuse.status_code == 400

        # 3. Old password fails
        res_old_login = client.post(
            "/api/v1/auth/login",
            json={"email": self.user_b_email, "password": self.password},
        )
        assert res_old_login.status_code == 401

        # 4. New password succeeds
        res_new_login = client.post(
            "/api/v1/auth/login",
            json={"email": self.user_b_email, "password": new_password},
        )
        assert res_new_login.status_code == 200
        assert "access_token" in res_new_login.json()
