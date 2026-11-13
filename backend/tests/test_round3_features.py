import hashlib
import hmac
import io
import json
import uuid
from unittest.mock import patch

import pymupdf
from fastapi.testclient import TestClient

from app.core.database import SessionLocal, init_db
from app.models.handover import Handover, HandoverClaim, HandoverSection
from app.models.knowledge import Decision, Dependency, KnowledgeDriftEvent
from app.models.workspace import Organization
from app.main import app
from app.services.code_ast_indexer import (
    parse_manifest_file,
    parse_python_source,
    parse_ts_js_source,
    persist_ast_graph_facts,
    summarize_repository_ast,
)
from app.services.connectors.github_connector import GitHubConnector
from app.services.email_service import email_service
from app.services.storage_service import storage_service

init_db()
client = TestClient(app)


def _setup_user():
    email = f"r3_user_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        "/api/v1/auth/register",
        json={"name": "Round3 Engineer", "email": email, "password": "StrongPassword123!"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    return headers, data["active_project_id"], data["user"]["org_id"]


def _cleanup(org_id: str):
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == org_id).first()
        if org:
            db.delete(org)
            db.commit()
    finally:
        db.close()


def test_code_ast_indexer_parses_python_ts_and_manifests():
    py_code = """
from fastapi import APIRouter
import redis

router = APIRouter()

class SessionCache:
    pass

@router.get("/health")
def check_health():
    return {"ok": True}
"""
    ts_code = """
import React from 'react'
import { api } from '@/lib/api'
export function ReadinessCard() { return null }
"""
    pkg_json = json.dumps({"dependencies": {"next": "16.0.0", "react": "19.0.0", "lucide-react": "0.4.0"}})

    py_parsed = parse_python_source("backend/app/main.py", py_code)
    assert "redis" in py_parsed["imports"]
    assert "SessionCache" in py_parsed["classes"]
    assert any("GET /health" in r for r in py_parsed["routes"])

    ts_parsed = parse_ts_js_source("frontend/components/ReadinessCard.tsx", ts_code)
    assert "react" in ts_parsed["imports"]
    assert "ReadinessCard" in ts_parsed["exports"]

    mf = parse_manifest_file("frontend/package.json", pkg_json)
    assert "next" in mf["dependencies"]

    summary = summarize_repository_ast(
        "acme/checkout",
        "main",
        [
            {"path": "backend/app/main.py", "content": py_code},
            {"path": "frontend/components/ReadinessCard.tsx", "content": ts_code},
            {"path": "frontend/package.json", "content": pkg_json},
        ],
        tree_paths=["backend/app/main.py", "frontend/components/ReadinessCard.tsx"],
    )
    assert len(summary["records"]) >= 1
    assert summary["records"][0]["source_type"] == "github_ast"
    assert "next" in summary["external_packages"]

    headers, project_id, org_id = _setup_user()
    try:
        db = SessionLocal()
        try:
            added = persist_ast_graph_facts(db, project_id, "acme/checkout", summary)
            db.commit()
            assert added >= 2
            deps = db.query(Dependency).filter(Dependency.project_id == project_id).all()
            assert len(deps) >= 1
        finally:
            db.close()
    finally:
        _cleanup(org_id)


def test_multimodal_diagram_image_upload_and_storage():
    headers, project_id, org_id = _setup_user()
    try:
        # Render a real 100x40 PNG architecture diagram image via PyMuPDF
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 40), False)
        pix.set_rect(pix.irect, (240, 240, 255))
        png_bytes = pix.tobytes("png")
        pix = None

        with patch(
            "app.services.ai_engine.ai_engine.extract_text_and_diagram_from_image",
            return_value={
                "ocr_text": "API Gateway -> Billing Service -> Supabase PostgreSQL",
                "ocr_performed": True,
                "ocr_provider": "gemini-3.5-flash-lite",
            },
        ):
            r = client.post(
                "/api/v1/documents/upload",
                headers=headers,
                data={"project_id": project_id, "title": "System Topology Diagram", "extract_knowledge": "false"},
                files={"file": ("topology.png", png_bytes, "image/png")},
            )
            assert r.status_code == 200, r.text
            doc = r.json()
            assert doc["file_type"] == "png"
            assert doc["chunk_count"] >= 1

        # Clean up uploaded object via DELETE endpoint
        r_del = client.delete(f"/api/v1/documents/{doc['id']}", headers=headers)
        assert r_del.status_code == 200
    finally:
        _cleanup(org_id)


def test_signed_webhooks_and_automated_knowledge_drift():
    headers, project_id, org_id = _setup_user()
    try:
        # Seed an accepted ADR Decision and a Handover Claim that will drift
        db = SessionLocal()
        try:
            dec = Decision(
                project_id=project_id,
                title="Use Redis Cluster for distributed checkout locking",
                summary="Adopted Redis Redlock across checkout workers for idempotent inventory locks.",
                reasoning="Low latency distributed locks.",
                decision_maker="Platform Lead",
                date="2026-10-01",
                component="Redis Cluster",
                status="accepted",
            )
            h = Handover(
                project_id=project_id,
                title="Checkout Handover",
                departing_employee_name="Alice",
                departing_employee_role="Lead",
                incoming_employee_name="Bob",
                incoming_employee_role="Senior Engineer",
                status="needs_review",
            )
            db.add(dec)
            db.add(h)
            db.flush()
            sec = HandoverSection(
                handover_id=h.id,
                section_number=1,
                title="Architecture",
                content="Uses Redis Cluster distributed locks.",
            )
            db.add(sec)
            db.flush()
            claim = HandoverClaim(
                handover_id=h.id,
                section_id=sec.id,
                claim_text="Checkout service depends on Redis Cluster Redlock distributed locking.",
                verification_status="Supported by Evidence",
                confidence=0.85,
            )
            db.add(claim)
            db.commit()
            claim_id = claim.id
        finally:
            db.close()

        # Connect GitHub integration & generate webhook signing secret
        with patch.object(
            GitHubConnector,
            "check_connection",
            return_value={"status": "connected", "login": "acme-bot", "connected_account": "acme-bot"},
        ):
            r_int = client.post(
                "/api/v1/integrations",
                headers=headers,
                json={
                    "project_id": project_id,
                    "provider": "github",
                    "name": "Checkout Repo",
                    "credentials": {"access_token": "ghp_dummy_webhook_test_token"},
                },
            )
        assert r_int.status_code == 200, r_int.text
        integ_id = r_int.json()["id"]

        r_wh = client.post(f"/api/v1/integrations/{integ_id}/webhook-config", headers=headers)
        assert r_wh.status_code == 200, r_wh.text
        secret = r_wh.json()["webhook_secret"]
        assert secret

        payload_bytes = json.dumps({
            "repository": {"full_name": "acme/checkout"},
            "ref": "refs/heads/main",
            "commits": [
                {
                    "id": "abc123456789",
                    "message": "Deprecated Redis Cluster distributed locking and migrated checkout locks to PostgreSQL advisory locks",
                    "author": {"name": "Bob"},
                    "modified": ["backend/locks.py"],
                }
            ],
        }).encode("utf-8")

        # Invalid signature MUST be rejected with 401
        r_bad = client.post(
            f"/api/v1/webhooks/github/{integ_id}",
            content=payload_bytes,
            headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": "sha256=deadbeef"},
        )
        assert r_bad.status_code == 401

        # Valid HMAC-SHA256 signature succeeds & triggers drift detection
        good_sig = "sha256=" + hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
        r_good = client.post(
            f"/api/v1/webhooks/github/{integ_id}",
            content=payload_bytes,
            headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": good_sig},
        )
        assert r_good.status_code == 200, r_good.text
        body = r_good.json()
        assert body["records"]["added"] == 1
        assert body["drift_detected"] >= 1

        # Verify drift alerts list & resolve workflow
        r_drift = client.get(f"/api/v1/knowledge/drift?project_id={project_id}&status=open", headers=headers)
        assert r_drift.status_code == 200
        alerts = r_drift.json()
        assert len(alerts) >= 1

        # Verify affected HandoverClaim was automatically marked Contradicted
        db = SessionLocal()
        try:
            refreshed_claim = db.query(HandoverClaim).filter(HandoverClaim.id == claim_id).first()
            assert refreshed_claim is not None
            assert refreshed_claim.verification_status == "Contradicted"
        finally:
            db.close()

        r_res = client.patch(
            f"/api/v1/knowledge/drift/{alerts[0]['id']}",
            headers=headers,
            json={"status": "resolved"},
        )
        assert r_res.status_code == 200
        assert r_res.json()["status"] == "resolved"
    finally:
        _cleanup(org_id)


def test_successor_readiness_simulator_and_capabilities_and_email():
    headers, project_id, org_id = _setup_user()
    try:
        # Check updated capabilities endpoint
        r_cap = client.get("/api/v1/auth/capabilities")
        assert r_cap.status_code == 200
        assert "supabase_storage_configured" in r_cap.json()

        # Check transactional email helper builds cleanly
        mail_res = email_service.send_handover_review_email(
            to_email="reviewer@example.com",
            reviewer_name="Tech Lead",
            handover_title="Core Service Handover",
            project_name="Core API",
            role="Tech Lead",
        )
        assert "provider" in mail_res

        # Reconstruct handover & run interactive readiness simulation
        r_rec = client.post(
            "/api/v1/handovers/reconstruct",
            headers=headers,
            json={
                "project_id": project_id,
                "departing_employee_name": "Alice Senior",
                "departing_employee_role": "Staff Engineer",
                "incoming_employee_name": "Bob Successor",
                "incoming_employee_role": "Senior Engineer",
            },
        )
        assert r_rec.status_code == 200, r_rec.text
        handover_id = r_rec.json()["id"]

        r_sim = client.get(f"/api/v1/handovers/{handover_id}/simulator", headers=headers)
        assert r_sim.status_code == 200, r_sim.text
        sim_data = r_sim.json()
        scenarios = sim_data["scenarios"]
        assert len(scenarios) == 3

        answers = {}
        for sc in scenarios:
            concepts = ", ".join(sc.get("expected_concepts") or [])
            answers[sc["id"]] = (
                f"For '{sc['title']}': "
                "1) Immediate Triage: Check structured application logs, container stderr, /health readiness endpoints, and HTTP 5xx/latency spikes. "
                "2) Blast Radius & Dependencies: Map affected upstream/downstream consumers in the Knowledge Graph, identify sole-owner components, and isolate failing workers or circuit-break timeouts cleanly. "
                "3) ADR & Constraint Verification: Audit prior Architectural Decision Records, check SHA-256 verified evidence chunks, confirm no undocumented schema or lock changes, and trigger safe rollback to the last green deployment revision if SLA degrades. "
                f"4) Governance & Recovery: Document root cause, verify post-rollback health metrics, assign a backup owner, and obtain stakeholder sign-off covering {concepts}."
            )

        r_eval = client.post(
            f"/api/v1/handovers/{handover_id}/simulator/evaluate",
            headers=headers,
            json={"candidate_name": "Bob Successor", "scenarios": scenarios, "answers": answers},
        )
        assert r_eval.status_code == 200, r_eval.text
        scorecard = r_eval.json()
        assert scorecard["overall_score"] >= 70.0
        assert scorecard["passed"] is True

        # Verify persisted into handover reconstruction_stats for approvals page
        r_h = client.get(f"/api/v1/handovers/{handover_id}", headers=headers)
        assert r_h.status_code == 200
        stats = r_h.json().get("reconstruction_stats") or {}
        assert stats.get("latest_readiness_score") == scorecard["overall_score"]
        assert stats.get("readiness_passed") == scorecard["passed"]
    finally:
        _cleanup(org_id)

