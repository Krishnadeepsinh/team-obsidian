"""Phase 3 verification tests: Multi-platform 16-section KT, Atomic Claims, Exit Interview, Delta Sync, 4-Dim Simulator & PDF Digest."""

from datetime import datetime, timezone
import hashlib
import uuid

from fastapi.testclient import TestClient

from app.core.database import SessionLocal, init_db
from app.main import app
from app.models.evidence import Evidence
from app.models.handover import (
    ExitInterviewQuestion,
    Handover,
    HandoverClaim,
    HandoverSection,
)
from app.models.integration import Integration, SourceRecord
from app.models.knowledge import (
    Decision,
    Dependency,
    EmbeddingRecord,
    KnowledgeDriftEvent,
    KnowledgeEntity,
    KnowledgeGap,
    KnowledgeRelationship,
    Responsibility,
    RiskItem,
    TaskItem,
)
from app.models.workspace import Organization, User
from app.services.ai_engine import ai_engine

init_db()
client = TestClient(app)


def _register_lead():
    email = f"p3kt_{uuid.uuid4().hex[:8]}@phase3kt.io"
    res = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Morgan Vance",
            "email": email,
            "password": "StrongPhase3KTPassword2026!",
            "role": "tech_lead",
            "title": "Principal Architect",
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


def _cleanup(email: str, project_id: str):
    db = SessionLocal()
    try:
        db.query(ExitInterviewQuestion).filter(ExitInterviewQuestion.project_id == project_id).delete(synchronize_session=False)
        db.query(HandoverClaim).filter(
            HandoverClaim.handover_id.in_(
                db.query(Handover.id).filter(Handover.project_id == project_id)
            )
        ).delete(synchronize_session=False)
        db.query(HandoverSection).filter(
            HandoverSection.handover_id.in_(
                db.query(Handover.id).filter(Handover.project_id == project_id)
            )
        ).delete(synchronize_session=False)
        db.query(Handover).filter(Handover.project_id == project_id).delete(synchronize_session=False)
        db.query(KnowledgeDriftEvent).filter(KnowledgeDriftEvent.project_id == project_id).delete(synchronize_session=False)
        db.query(KnowledgeGap).filter(KnowledgeGap.project_id == project_id).delete(synchronize_session=False)
        db.query(KnowledgeRelationship).filter(KnowledgeRelationship.project_id == project_id).delete(synchronize_session=False)
        db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == project_id).delete(synchronize_session=False)
        db.query(EmbeddingRecord).filter(EmbeddingRecord.project_id == project_id).delete(synchronize_session=False)
        db.query(TaskItem).filter(TaskItem.project_id == project_id).delete(synchronize_session=False)
        db.query(Decision).filter(Decision.project_id == project_id).delete(synchronize_session=False)
        db.query(Dependency).filter(Dependency.project_id == project_id).delete(synchronize_session=False)
        db.query(Responsibility).filter(Responsibility.project_id == project_id).delete(synchronize_session=False)
        db.query(RiskItem).filter(RiskItem.project_id == project_id).delete(synchronize_session=False)
        db.query(Evidence).filter(Evidence.project_id == project_id).delete(synchronize_session=False)
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


def _seed_multiplatform_project(db, project_id: str, user_id: str):
    now = datetime.now(timezone.utc)
    integ = Integration(
        project_id=project_id,
        user_id=user_id,
        provider="gitlab",
        name="GitLab & Jira Suite",
        status="connected",
    )
    db.add(integ)
    db.flush()

    person_ent = KnowledgeEntity(
        project_id=project_id,
        entity_type="person",
        name="Alice Smith",
        properties={"aliases": ["alice-dev", "alice.smith@acme.io"]},
        confidence=0.95,
    )
    comp_ent = KnowledgeEntity(
        project_id=project_id,
        entity_type="component",
        name="Billing Ledger Worker",
        description="Idempotent Stripe webhook consumer & settlement job",
        confidence=0.9,
    )
    db.add_all([person_ent, comp_ent])
    db.flush()
    db.add(
        KnowledgeRelationship(
            project_id=project_id,
            source_entity_id=person_ent.id,
            target_entity_id=comp_ent.id,
            relation_type="owns",
            context="Sole maintainer of billing ledger consumer",
            confidence=0.94,
        )
    )

    records = [
        SourceRecord(
            integration_id=integ.id,
            project_id=project_id,
            source_type="gitlab_mr",
            external_id="mr-401",
            title="MR !401: Harden idempotency key TTL for billing worker",
            url="https://gitlab.acme.io/billing/ledger/-/merge_requests/401",
            author="alice-dev",
            source_timestamp=now,
            content="Moves Redis idempotency lock TTL to 24h in billing-ledger worker.",
            metadata_json={"state": "merged"},
            sha256_hash=hashlib.sha256(b"mr-401").hexdigest(),
        ),
        SourceRecord(
            integration_id=integ.id,
            project_id=project_id,
            source_type="jira_issue",
            external_id="FIN-88",
            title="[FIN-88] Reconcile settlement retries after Stripe webhook timeout",
            url="https://acme.atlassian.net/browse/FIN-88",
            author="Alice Smith",
            source_timestamp=now,
            content="Status: In Progress. Settlement retries require manual DLQ replay.",
            sha256_hash=hashlib.sha256(b"FIN-88").hexdigest(),
        ),
        SourceRecord(
            integration_id=integ.id,
            project_id=project_id,
            source_type="sentry_issue",
            external_id="SENTRY-992",
            title="PGPoolTimeout on Billing Ledger Worker",
            url="https://sentry.io/organizations/acme/issues/992/",
            author="sentry-bot",
            source_timestamp=now,
            content="Connection pool exhausted during Friday batch settlement.",
            sha256_hash=hashlib.sha256(b"SENTRY-992").hexdigest(),
        ),
    ]
    db.add_all(records)
    db.flush()

    ev1 = Evidence(
        project_id=project_id,
        source_record_id=records[0].id,
        source_type="gitlab_mr",
        source_id="mr-401",
        source_title="MR !401: Harden idempotency key TTL for billing worker",
        source_author="alice-dev",
        claim_type="code_change",
        excerpt="Billing Ledger Worker enforces 24h Redis idempotency lock TTL to prevent double charges.",
        ai_interpretation="Idempotency guard verified in GitLab MR !401.",
        confidence=0.92,
        verification_status="Verified by Reviewer",
        content_hash=hashlib.sha256(b"ev1-gitlab").hexdigest(),
    )
    ev2 = Evidence(
        project_id=project_id,
        source_type="repo_config",
        source_id="cfg-worker",
        source_title="deploy/billing-worker.yaml",
        source_author="alice-dev",
        claim_type="deployment_config",
        excerpt="GITLAB_MIRROR=https://gitlab.acme.io/billing/ledger SENTRY_DSN=https://ingest.sentry.io/99",
        ai_interpretation="Billing worker GitLab CI & Sentry telemetry endpoints.",
        confidence=0.88,
        verification_status="Supported by Evidence",
        content_hash=hashlib.sha256(b"ev2-cfg").hexdigest(),
    )
    db.add_all([ev1, ev2])
    db.flush()

    db.add(
        TaskItem(
            project_id=project_id,
            title="Drain billing DLQ before Redis upgrade",
            description="Run dlq_replay.py --dry-run on Billing Ledger Worker before upgrading Redis cluster.",
            owner="alice-dev",
            component="Billing Ledger Worker",
            priority="critical",
            status="open",
            evidence_ids=[ev1.id],
        )
    )
    db.add(
        Decision(
            project_id=project_id,
            title="Adopt Redis-backed Idempotency Keys for Settlement",
            summary="Chose Redis SETNX with 24h TTL over PostgreSQL advisory locks for webhook deduplication.",
            reasoning="Sub-millisecond contention check under Friday settlement spikes.",
            date="2026-10-14",
            decision_maker="Alice Smith",
            confidence=0.9,
            evidence_ids=[ev1.id],
        )
    )
    db.add(
        RiskItem(
            project_id=project_id,
            title="PGPool saturation on Billing Ledger Worker",
            description="Batch settlement exhausts PG connections above 80 concurrent workers.",
            severity="critical",
            mitigation_strategy="Cap worker concurrency at 32 and route reads through pgbouncer.",
            owner="Alice Smith",
            evidence_ids=[ev1.id],
        )
    )
    db.add(
        Dependency(
            project_id=project_id,
            source_component="Billing Ledger Worker",
            target_component="Stripe Webhook Gateway",
            dependency_type="hard_blocker",
            description="Consumes signed settlement events",
            owner="Alice Smith",
            criticality="critical",
            evidence_ids=[ev1.id],
        )
    )
    db.add(
        Responsibility(
            project_id=project_id,
            owner="Alice Smith",
            domain="Billing Ledger Worker",
            scope="On-call triage, webhook replay, settlement integrity",
            criticality="critical",
            backup_owner=None,
            evidence_ids=[ev1.id],
        )
    )
    db.add(
        KnowledgeGap(
            project_id=project_id,
            gap_type="missing_runbook",
            severity="critical",
            title="Undocumented Stripe Webhook Secret Rotation Steps",
            description="No step-by-step zero-downtime webhook signing secret rotation procedure is documented.",
            impact="Secret rotation could drop live settlement webhooks.",
            recommended_action="Capture dual-secret overlap window procedure from Alice Smith.",
            status="identified",
        )
    )
    db.commit()


def test_phase3_full_kt_lifecycle_exit_interview_delta_sync_simulator_and_pdf():
    ctx = _register_lead()
    headers = ctx["headers"]
    project_id = ctx["project_id"]

    orig_get_client = ai_engine._get_client
    # Ensure deterministic offline/fast execution in tests regardless of Gemini quota/latency
    ai_engine._get_client = lambda: None
    try:
        db = SessionLocal()
        try:
            _seed_multiplatform_project(db, project_id, ctx["user_id"])
        finally:
            db.close()

        # 1. Multi-platform 16-section reconstruction + Atomic Claims
        res = client.post(
            "/api/v1/handovers/reconstruct",
            headers=headers,
            json={
                "project_id": project_id,
                "departing_employee_name": "Alice Smith",
                "departing_employee_role": "Staff Billing Engineer",
                "incoming_employee_name": "Morgan Vance",
                "incoming_employee_role": "Principal Architect",
                "selected_sources": ["github", "gitlab", "jira", "sentry"],
            },
        )
        assert res.status_code == 200, res.text
        handover = res.json()
        handover_id = handover["id"]
        sections = handover["sections"]
        assert len(sections) == 16

        sec3 = next(s for s in sections if s["section_number"] == 3)
        assert "Harden idempotency key TTL" in sec3["content"], sec3["content"]

        sec5 = next(s for s in sections if s["section_number"] == 5)
        assert "Drain billing DLQ" in sec5["content"], "Identity alias alice-dev task missing from Section 5"

        sec10 = next(s for s in sections if s["section_number"] == 10)
        assert "jira_issue" in sec10["content"] and "sentry_issue" in sec10["content"], sec10["content"]

        sec2 = next(s for s in sections if s["section_number"] == 2)
        assert len(sec2["claims"]) >= 1
        assert any(len(c.get("evidence_ids") or []) > 0 for c in sec2["claims"])

        # 2. Interactive Exit Interview -> verified Evidence + Embedding + Gap resolved
        ei_res = client.get(f"/api/v1/handovers/{handover_id}/exit-interview", headers=headers)
        assert ei_res.status_code == 200, ei_res.text
        questions = ei_res.json()
        assert len(questions) >= 1
        gap_q = next((q for q in questions if q.get("knowledge_gap_id")), questions[0])

        ans_res = client.post(
            f"/api/v1/handovers/{handover_id}/exit-interview/{gap_q['id']}/answer",
            headers=headers,
            json={
                "answer_text": "Rotate STRIPE_WEBHOOK_SECRET by configuring dual secrets in Vault for 30 minutes before revoking the legacy key.",
                "resolve_linked_gap": True,
            },
        )
        assert ans_res.status_code == 200, ans_res.text
        answered = ans_res.json()
        assert answered["status"] == "answered"
        assert answered["evidence_id"]

        db = SessionLocal()
        try:
            ev = db.query(Evidence).filter(Evidence.id == answered["evidence_id"]).first()
            assert ev is not None
            assert ev.source_type == "exit_interview"
            assert ev.verification_status == "Verified by Reviewer"
            emb = (
                db.query(EmbeddingRecord)
                .filter(EmbeddingRecord.entity_type == "evidence", EmbeddingRecord.entity_id == ev.id)
                .first()
            )
            assert emb is not None
            if gap_q.get("knowledge_gap_id"):
                gap_row = db.query(KnowledgeGap).filter(KnowledgeGap.id == gap_q["knowledge_gap_id"]).first()
                assert gap_row.status == "resolved"

            # Prepare verified Section 1 + open DriftEvent for Living Delta Sync test
            sec1_row = (
                db.query(HandoverSection)
                .filter(HandoverSection.handover_id == handover_id, HandoverSection.section_number == 1)
                .first()
            )
            sec1_row.is_verified = True
            sec1_row.verification_status = "Verified by Reviewer"
            sec1_row.content = "HUMAN VERIFIED EXEC SUMMARY: Keep dual-secret rotation check active."
            clm_row = db.query(HandoverClaim).filter(HandoverClaim.id == sec2["claims"][0]["id"]).first()
            clm_row.verification_status = "Contradicted"
            db.add(
                KnowledgeDriftEvent(
                    project_id=project_id,
                    drift_type="contradiction",
                    severity="high",
                    target_entity_type="handover_claim",
                    target_entity_id=sec2["claims"][0]["id"],
                    target_title="Settlement TTL drift",
                    summary="Recent commit mentions 48h TTL override.",
                    status="open",
                )
            )
            db.commit()
        finally:
            db.close()

        # 3. Living Dossier Delta Sync -> preserves verified section, refreshes unverified, clears drift
        sync_res = client.post(f"/api/v1/handovers/{handover_id}/delta-sync", headers=headers)
        assert sync_res.status_code == 200, sync_res.text
        sync_data = sync_res.json()
        assert 1 in sync_data["preserved_sections"]
        assert 2 in sync_data["updated_sections"]
        assert sync_data["drift_warnings_cleared"] >= 1

        ho_after = client.get(f"/api/v1/handovers/{handover_id}", headers=headers).json()
        sec1_after = next(s for s in ho_after["sections"] if s["section_number"] == 1)
        assert "HUMAN VERIFIED EXEC SUMMARY" in sec1_after["content"]

        # 4. Readiness Simulator 4-Dimension Rubric, Follow-ups & Automatic Gap Remediation
        gen_res = client.get(f"/api/v1/handovers/{handover_id}/simulator?regenerate=true", headers=headers)
        assert gen_res.status_code == 200, gen_res.text
        scenarios = gen_res.json()["scenarios"]
        assert len(scenarios) >= 1
        assert scenarios[0].get("follow_up_question")

        weak_answers = {s["id"]: "Restart the server and check logs." for s in scenarios}
        weak_eval = client.post(
            f"/api/v1/handovers/{handover_id}/simulator/evaluate",
            headers=headers,
            json={"answers": weak_answers},
        )
        assert weak_eval.status_code == 200, weak_eval.text
        weak_body = weak_eval.json()
        assert weak_body["overall_score"] < 60
        assert weak_body["passed"] is False
        rubric = weak_body["responses"][0]["rubric_breakdown"]
        for key in ("architecture_accuracy", "blast_radius_awareness", "mitigation_readiness", "operational_specificity"):
            assert key in rubric
        assert weak_body["dimension_averages"] is not None
        assert len(weak_body["remediation_gaps_created"]) >= 1

        strong_answers = {
            s["id"]: (
                "Billing Ledger Worker connects to Stripe Webhook Gateway and Redis idempotency locks. "
                "Mitigation: check pgbouncer pool limits, drain DLQ via dlq_replay.py --dry-run, verify 24h TTL, "
                "and rollback feature flag before paging secondary on-call."
            )
            for s in scenarios
        }
        follow_ups = {
            s["id"]: "Confirmed verification by checking Stripe webhook 200 ACK rate and Redis SETNX hit metrics."
            for s in scenarios
        }
        strong_eval = client.post(
            f"/api/v1/handovers/{handover_id}/simulator/evaluate",
            headers=headers,
            json={"answers": strong_answers, "follow_ups": follow_ups},
        )
        assert strong_eval.status_code == 200, strong_eval.text
        assert strong_eval.json()["overall_score"] > weak_body["overall_score"]

        # 5. Tamper-Evident PDF Export with SPOF & Claims tables + X-Document-SHA256
        pdf_res = client.get(f"/api/v1/handovers/{handover_id}/pdf", headers=headers)
        assert pdf_res.status_code == 200, pdf_res.text
        assert pdf_res.headers.get("content-type", "").startswith("application/pdf")
        digest = pdf_res.headers.get("x-document-sha256")
        assert digest and len(digest) == 64
        assert pdf_res.content.startswith(b"%PDF")
    finally:
        ai_engine._get_client = orig_get_client
        _cleanup(ctx["email"], project_id)

