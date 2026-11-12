import uuid
from fastapi.testclient import TestClient

from app.core.database import SessionLocal, init_db
from app.main import app
from app.models.knowledge import KnowledgeEntity, KnowledgeRelationship
from app.models.workspace import Organization, User

init_db()
client = TestClient(app)


def _register(role: str = "tech_lead", prefix: str = "p1graph"):
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@phase1-test.io"
    res = client.post(
        "/api/v1/auth/register",
        json={
            "name": f"{prefix.title()} Engineer",
            "email": email,
            "password": "StrongPhase1Password2026!",
            "role": role,
            "title": "Staff Engineer",
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


def test_phase1_departure_simulation_backup_mitigation_and_mermaid_export():
    owner = _register(role="tech_lead", prefix="owner")
    outsider = _register(role="developer", prefix="outsider")
    viewer = _register(role="viewer", prefix="viewer")

    try:
        db = SessionLocal()
        pid = owner["project_id"]
        alice = KnowledgeEntity(project_id=pid, entity_type="person", name="Alice Lin", confidence=0.95)
        gateway = KnowledgeEntity(project_id=pid, entity_type="service", name="Payment Gateway", confidence=0.92)
        ledger = KnowledgeEntity(project_id=pid, entity_type="database", name="Ledger DB", confidence=0.9)
        isolated = KnowledgeEntity(project_id=pid, entity_type="component", name="Legacy Cron", confidence=0.7)
        db.add_all([alice, gateway, ledger, isolated])
        db.flush()

        r1 = KnowledgeRelationship(
            project_id=pid,
            source_entity_id=alice.id,
            target_entity_id=gateway.id,
            relation_type="owns",
            confidence=0.95,
        )
        r2 = KnowledgeRelationship(
            project_id=pid,
            source_entity_id=gateway.id,
            target_entity_id=ledger.id,
            relation_type="depends_on",
            confidence=0.9,
        )
        db.add_all([r1, r2])
        db.commit()
        alice_id, gateway_id = alice.id, gateway.id
        db.close()

        # 1. React Flow vertical & horizontal + hide_isolated
        r_rf = client.get(
            f"/api/v1/graph/react-flow?project_id={pid}&layout=horizontal&hide_isolated=true",
            headers=owner["headers"],
        )
        assert r_rf.status_code == 200, r_rf.text
        rf_data = r_rf.json()
        assert rf_data["stats"]["layout"] == "horizontal"
        assert rf_data["stats"]["hidden_isolated_count"] == 1
        assert len(rf_data["nodes"]) == 3
        assert len(rf_data["spof_warnings"]) == 1
        assert rf_data["people"][0]["name"] == "Alice Lin"
        assert rf_data["people"][0]["spof_count"] == 1

        # 2. Simulate Alice's departure -> Payment Gateway orphaned, Ledger DB downstream impacted
        r_dep = client.get(f"/api/v1/graph/departure-impact/{alice_id}", headers=owner["headers"])
        assert r_dep.status_code == 200, r_dep.text
        dep = r_dep.json()
        assert dep["person_name"] == "Alice Lin"
        assert len(dep["orphaned_spofs"]) == 1
        assert dep["orphaned_spofs"][0]["id"] == gateway_id
        assert dep["bus_factor_risk_score"] > 0
        assert any(e["name"] == "Ledger DB" for e in dep["affected_entities"])

        # 3. Cross-tenant & viewer RBAC checks
        assert client.get(f"/api/v1/graph/departure-impact/{alice_id}", headers=outsider["headers"]).status_code == 403
        assert client.post(
            "/api/v1/graph/assign-backup-owner",
            headers=outsider["headers"],
            json={"component_id": gateway_id, "backup_person_name": "Mallory"},
        ).status_code == 403
        assert client.post(
            "/api/v1/graph/assign-backup-owner",
            headers=viewer["headers"],
            json={"component_id": gateway_id, "backup_person_name": "ViewerBob"},
        ).status_code == 403

        # 4. Owner assigns Bob Patel as backup maintainer -> SPOF mitigated!
        r_bk = client.post(
            "/api/v1/graph/assign-backup-owner",
            headers=owner["headers"],
            json={"component_id": gateway_id, "backup_person_name": "Bob Patel", "relation_type": "maintains"},
        )
        assert r_bk.status_code == 200, r_bk.text
        bk_data = r_bk.json()
        assert bk_data["is_still_spof"] is False
        assert bk_data["remaining_spof_count"] == 0

        # Re-simulating Alice's departure now shows zero orphaned SPOFs and 0% bus-factor risk
        r_dep2 = client.get(f"/api/v1/graph/departure-impact/{alice_id}", headers=owner["headers"])
        assert r_dep2.status_code == 200
        assert len(r_dep2.json()["orphaned_spofs"]) == 0
        assert r_dep2.json()["bus_factor_risk_score"] == 0

        # 5. Mermaid export contains expected nodes/edges and blocks outsiders
        r_mmd = client.get(f"/api/v1/graph/export/mermaid?project_id={pid}", headers=owner["headers"])
        assert r_mmd.status_code == 200, r_mmd.text
        assert "flowchart TD" in r_mmd.json()["mermaid"]
        assert "Payment Gateway" in r_mmd.json()["mermaid"]
        assert client.get(f"/api/v1/graph/export/mermaid?project_id={pid}", headers=outsider["headers"]).status_code == 403
    finally:
        _cleanup(owner["email"], outsider["email"], viewer["email"])

