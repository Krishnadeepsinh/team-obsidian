"""Phase 2 verification tests: Identity Stitching, Watermarked Extraction, Weighted SPOF & Drift."""

from datetime import datetime, timedelta, timezone
import hashlib
import uuid

from app.core.database import SessionLocal, init_db
from app.models.evidence import Evidence
from app.models.handover import Handover, HandoverClaim, HandoverSection
from app.models.integration import Integration, SourceRecord
from app.models.knowledge import (
    Decision,
    Dependency,
    KnowledgeDriftEvent,
    KnowledgeEntity,
    KnowledgeGap,
    KnowledgeRelationship,
    Responsibility,
    RiskItem,
    TaskItem,
)
from app.models.workspace import Notification, Organization, Project, User, Workspace
from app.services.ai_engine import StructuredKnowledgeBundle, ai_engine
from app.services.drift_detector import scan_project_for_drift
from app.services.graph_service import graph_service
from app.services.identity_resolver import (
    build_project_identity_map,
    merge_duplicate_person_entities,
    resolve_author_name,
)
from app.services.ingestion_service import upsert_source_records
from app.services.knowledge_extractor import extract_and_persist_project_knowledge


def _seed(db, suffix: str):
    org = Organization(name=f"P2Org-{suffix}", slug=f"p2org-{suffix}")
    db.add(org)
    db.flush()
    user = User(
        org_id=org.id,
        email=f"alice.smith+{suffix}@acme.io",
        password_hash="x",
        name="Alice Smith",
        role="tech_lead",
        is_active=True,
    )
    db.add(user)
    db.flush()
    ws = Workspace(org_id=org.id, name=f"P2WS-{suffix}", slug=f"p2ws-{suffix}", owner_id=user.id)
    db.add(ws)
    db.flush()
    project = Project(
        workspace_id=ws.id,
        creator_id=user.id,
        name=f"P2Proj-{suffix}",
        slug=f"p2proj-{suffix}",
        description="Phase 2 KT test project",
    )
    db.add(project)
    db.flush()
    integ = Integration(
        project_id=project.id,
        user_id=user.id,
        provider="github",
        name="GitHub Repo",
        status="connected",
    )
    db.add(integ)
    db.commit()
    return org, user, project, integ


def _cleanup(db, org_id: str):
    db.rollback()
    ws_ids = [w.id for w in db.query(Workspace).filter(Workspace.org_id == org_id).all()]
    proj_ids = [p.id for p in db.query(Project).filter(Project.workspace_id.in_(ws_ids)).all()] if ws_ids else []
    for pid in proj_ids:
        ho_ids = [h.id for h in db.query(Handover).filter(Handover.project_id == pid).all()]
        if ho_ids:
            db.query(HandoverClaim).filter(HandoverClaim.handover_id.in_(ho_ids)).delete(synchronize_session=False)
            db.query(HandoverSection).filter(HandoverSection.handover_id.in_(ho_ids)).delete(synchronize_session=False)
            db.query(Handover).filter(Handover.id.in_(ho_ids)).delete(synchronize_session=False)
        db.query(Notification).filter(Notification.project_id == pid).delete(synchronize_session=False)
        db.query(KnowledgeDriftEvent).filter(KnowledgeDriftEvent.project_id == pid).delete(synchronize_session=False)
        db.query(KnowledgeRelationship).filter(KnowledgeRelationship.project_id == pid).delete(synchronize_session=False)
        db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == pid).delete(synchronize_session=False)
        db.query(Decision).filter(Decision.project_id == pid).delete(synchronize_session=False)
        db.query(Dependency).filter(Dependency.project_id == pid).delete(synchronize_session=False)
        db.query(Responsibility).filter(Responsibility.project_id == pid).delete(synchronize_session=False)
        db.query(RiskItem).filter(RiskItem.project_id == pid).delete(synchronize_session=False)
        db.query(TaskItem).filter(TaskItem.project_id == pid).delete(synchronize_session=False)
        db.query(KnowledgeGap).filter(KnowledgeGap.project_id == pid).delete(synchronize_session=False)
        db.query(Evidence).filter(Evidence.project_id == pid).delete(synchronize_session=False)
        db.query(SourceRecord).filter(SourceRecord.project_id == pid).delete(synchronize_session=False)
        db.query(Integration).filter(Integration.project_id == pid).delete(synchronize_session=False)
    if proj_ids:
        db.query(Project).filter(Project.id.in_(proj_ids)).delete(synchronize_session=False)
    if ws_ids:
        db.query(Workspace).filter(Workspace.id.in_(ws_ids)).delete(synchronize_session=False)
    db.query(User).filter(User.org_id == org_id).delete(synchronize_session=False)
    db.query(Organization).filter(Organization.id == org_id).delete(synchronize_session=False)
    db.commit()


def test_cross_platform_identity_stitching_and_entity_merge():
    init_db()
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    org = None
    try:
        org, _, project, integ = _seed(db, suffix)
        # Seed records authored across GitHub, Slack, Jira under different aliases for Alice Smith
        # plus two distinct Bobs that must NOT be falsely merged.
        recs = [
            SourceRecord(
                integration_id=integ.id,
                project_id=project.id,
                source_type="github_pr",
                external_id=f"gh-{suffix}",
                title="PR #12: Payment webhook retry",
                author="alice-dev",
                content="Implements retry queue",
                sha256_hash="h1",
                metadata_json={"email": "alice.smith@acme.io", "name": "Alice Smith"},
            ),
            SourceRecord(
                integration_id=integ.id,
                project_id=project.id,
                source_type="slack_message",
                external_id=f"sl-{suffix}",
                title="Thread on retries",
                author="@alice",
                content="Confirmed failover",
                sha256_hash="h2",
                metadata_json={"real_name": "Alice Smith"},
            ),
            SourceRecord(
                integration_id=integ.id,
                project_id=project.id,
                source_type="jira_issue",
                external_id=f"jr1-{suffix}",
                title="Ticket B1",
                author="Bob Chen",
                content="Redis work",
                sha256_hash="h3",
            ),
            SourceRecord(
                integration_id=integ.id,
                project_id=project.id,
                source_type="jira_issue",
                external_id=f"jr2-{suffix}",
                title="Ticket B2",
                author="Bob Miller",
                content="Billing work",
                sha256_hash="h4",
            ),
        ]
        db.add_all(recs)

        e_svc = KnowledgeEntity(project_id=project.id, entity_type="component", name="payment-webhook")
        e_alice1 = KnowledgeEntity(project_id=project.id, entity_type="person", name="@alice")
        e_alice2 = KnowledgeEntity(project_id=project.id, entity_type="person", name="alice.smith@acme.io")
        e_alice3 = KnowledgeEntity(project_id=project.id, entity_type="person", name="Alice Smith")
        db.add_all([e_svc, e_alice1, e_alice2, e_alice3])
        db.flush()

        db.add_all([
            KnowledgeRelationship(project_id=project.id, source_entity_id=e_alice1.id, target_entity_id=e_svc.id, relation_type="maintains"),
            KnowledgeRelationship(project_id=project.id, source_entity_id=e_alice2.id, target_entity_id=e_svc.id, relation_type="owns"),
            KnowledgeRelationship(project_id=project.id, source_entity_id=e_alice3.id, target_entity_id=e_svc.id, relation_type="owns"),
        ])
        db.commit()

        id_map = build_project_identity_map(project.id, db)
        assert resolve_author_name("alice-dev", id_map) == "Alice Smith"
        assert resolve_author_name("@alice", id_map) == "Alice Smith"
        assert resolve_author_name("alice.smith@acme.io", id_map) == "Alice Smith"
        assert resolve_author_name("Bob Chen", id_map) == "Bob Chen"
        assert resolve_author_name("Bob Miller", id_map) == "Bob Miller"

        merged = merge_duplicate_person_entities(db, project.id, identity_map=id_map)
        db.commit()
        assert merged == 2

        remaining_people = (
            db.query(KnowledgeEntity)
            .filter(KnowledgeEntity.project_id == project.id, KnowledgeEntity.entity_type == "person")
            .all()
        )
        assert len(remaining_people) == 1
        assert remaining_people[0].name == "Alice Smith"
        # Duplicate 'owns' rel must be deduplicated cleanly while preserving 'maintains' + 'owns'
        rels = db.query(KnowledgeRelationship).filter(KnowledgeRelationship.project_id == project.id).all()
        assert len(rels) == 2
        assert {r.relation_type for r in rels} == {"owns", "maintains"}
    finally:
        if org is not None:
            _cleanup(db, org.id)
        db.close()


def test_watermarked_incremental_extraction_and_bidirectional_sync():
    init_db()
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    org = None
    orig_extract = ai_engine.extract_knowledge_from_records
    batch_counter = {"n": 0}

    def _mock_extract(records, project_name="Project"):
        idx = batch_counter["n"]
        batch_counter["n"] += 1
        return StructuredKnowledgeBundle.model_validate(
            {
                "decisions": [
                    {
                        "title": f"Use Postgres Shard Ledger Batch {idx}",
                        "summary": f"Selected Postgres ledger for svc-batch-{idx}",
                        "reasoning": "ACID guarantees required",
                        "decision_maker": "alice.smith@acme.io",
                        "component": f"svc-batch-{idx}",
                        "evidence_index": 1,
                    }
                ],
                "dependencies": [
                    {
                        "source_component": f"svc-batch-{idx}",
                        "target_component": "postgres-core",
                        "dependency_type": "hard_blocker",
                        "description": "Primary ledger store",
                        "owner": "@alice",
                        "criticality": "high",
                        "evidence_index": 1,
                    }
                ],
                "responsibilities": [
                    {
                        "owner": "alice.smith@acme.io",
                        "domain": f"svc-batch-{idx}",
                        "scope": "Primary service ownership",
                        "criticality": "high",
                        "backup_owner": "Bob Chen",
                        "evidence_index": 1,
                    }
                ],
            }
        )

    ai_engine.extract_knowledge_from_records = _mock_extract
    try:
        org, user, project, integ = _seed(db, suffix)
        # Ingest 18 distinct records (> old hardcoded max_records=15 limit)
        raw_records = []
        for idx in range(18):
            body = (
                f"Decision: Service svc-{idx} depends on postgres-core because Shard {idx} requires ACID ledger.\n"
                f"Action: Complete migration task-{idx} for svc-{idx}.\n"
                f"Risk: Single point of failure on svc-{idx} owned by @alice."
            )
            raw_records.append(
                {
                    "source_type": "github_pr",
                    "external_id": f"pr-{suffix}-{idx}",
                    "title": f"PR #{idx}: Architecture change for svc-{idx}",
                    "content": body,
                    "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    "author": "alice.smith@acme.io" if idx % 2 == 0 else "Alice Smith",
                    "url": f"https://github.com/acme/core/pull/{idx}",
                    "metadata": {},
                }
            )
        upsert_source_records(db, integ, raw_records)
        db.commit()

        counts1 = extract_and_persist_project_knowledge(db, project.id, actor_user_id=user.id, max_records=10, full_sweep=True)
        assert counts1["batches_processed"] >= 2
        assert counts1["records_processed"] == 18

        # All 18 SourceRecords should now be watermarked
        unwatermarked = (
            db.query(SourceRecord)
            .filter(SourceRecord.project_id == project.id, SourceRecord.extraction_processed_at.is_(None))
            .count()
        )
        assert unwatermarked == 0

        # Bidirectional check: Dependency/Decision/Responsibility should produce KnowledgeRelationships
        rels = db.query(KnowledgeRelationship).filter(KnowledgeRelationship.project_id == project.id).all()
        assert len(rels) > 0

        # Re-running incremental extraction immediately should skip all watermarked records
        counts2 = extract_and_persist_project_knowledge(db, project.id, actor_user_id=user.id)
        assert counts2["records_processed"] == 0
        assert counts2["batches_processed"] == 0
    finally:
        ai_engine.extract_knowledge_from_records = orig_extract
        if org is not None:
            _cleanup(db, org.id)
        db.close()


def test_weighted_ownership_spof_and_busfactor():
    entities = [
        {"id": "p-alice", "name": "Alice Smith", "entity_type": "person"},
        {"id": "p-carol", "name": "Carol Tan", "entity_type": "person"},
        {"id": "c-solo", "name": "auth-core", "entity_type": "service"},
        {"id": "c-concentrated", "name": "ledger-db", "entity_type": "database"},
        {"id": "c-shared", "name": "api-edge", "entity_type": "service"},
        {"id": "c-downstream", "name": "billing-ui", "entity_type": "component"},
    ]
    relationships = [
        # Sole 100% owner with downstream consumers
        {"source_entity_id": "p-alice", "target_entity_id": "c-solo", "relation_type": "owns", "confidence": 1.0},
        {"source_entity_id": "c-solo", "target_entity_id": "c-downstream", "relation_type": "depends_on"},
        # Heavy concentration: Alice owns+maintains+decided (~1.4+) vs Carol tiny low-conf contributes (0.35*0.4=0.14) -> >88% Alice share
        {"source_entity_id": "p-alice", "target_entity_id": "c-concentrated", "relation_type": "owns", "confidence": 1.0},
        {"source_entity_id": "p-alice", "target_entity_id": "c-concentrated", "relation_type": "maintains", "confidence": 1.0},
        {"source_entity_id": "p-carol", "target_entity_id": "c-concentrated", "relation_type": "contributes", "confidence": 0.4},
        # Balanced shared ownership (Alice owns 1.0, Carol maintains 0.85 -> 54% / 46%, NOT SPOF)
        {"source_entity_id": "p-alice", "target_entity_id": "c-shared", "relation_type": "owns", "confidence": 1.0},
        {"source_entity_id": "p-carol", "target_entity_id": "c-shared", "relation_type": "maintains", "confidence": 1.0},
    ]

    spofs = graph_service.detect_single_points_of_failure(entities, relationships)
    spof_by_comp = {s["component_id"]: s for s in spofs}

    assert "c-solo" in spof_by_comp
    assert spof_by_comp["c-solo"]["effective_bus_factor"] == 1.0
    assert spof_by_comp["c-solo"]["ownership_share"] == 1.0

    assert "c-concentrated" in spof_by_comp
    assert spof_by_comp["c-concentrated"]["sole_owner"] == "Alice Smith"
    assert spof_by_comp["c-concentrated"]["ownership_share"] >= 0.80
    assert spof_by_comp["c-concentrated"]["effective_bus_factor"] < 1.5

    assert "c-shared" not in spof_by_comp

    sim = graph_service.simulate_person_departure(entities, relationships, "p-alice")
    orphaned_ids = {o["id"] for o in sim["orphaned_spofs"]}
    backed_ids = {b["id"] for b in sim["backed_up_components"]}
    assert "c-solo" in orphaned_ids
    assert "c-concentrated" in orphaned_ids
    assert "c-shared" in backed_ids
    assert sim["bus_factor_risk_score"] > 0


def test_semantic_and_temporal_drift_invalidates_handover_claims():
    init_db()
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    org = None
    try:
        org, user, project, integ = _seed(db, suffix)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        old_ts = now - timedelta(days=30)
        new_ts = now + timedelta(minutes=5)

        ho = Handover(
            project_id=project.id,
            created_by_user_id=user.id,
            title="Core Services KT",
            departing_employee_name="Alice Smith",
            departing_employee_role="Staff Engineer",
            incoming_employee_name="Bob Chen",
            incoming_employee_role="Senior Engineer",
            status="review",
            reconstruction_stats={},
        )
        db.add(ho)
        db.flush()

        sec = HandoverSection(
            handover_id=ho.id,
            section_number=1,
            title="Messaging Architecture",
            content="Payment webhook retries run through RabbitMQ dead-letter queue.",
        )
        db.add(sec)
        db.flush()

        claim = HandoverClaim(
            handover_id=ho.id,
            section_id=sec.id,
            claim_text="Payment webhook retries rely on RabbitMQ dead-letter queue backoff workers.",
            verification_status="Verified by Reviewer",
            confidence=0.92,
            evidence_ids=[],
        )
        db.add(claim)
        db.flush()
        # Ensure claim created_at is explicitly anchored to now for temporal comparison
        claim.created_at = now
        claim.updated_at = now

        # 1. Historical pre-claim source (older than claim) must NOT contradict the newer claim
        historical_rec = SourceRecord(
            integration_id=integ.id,
            project_id=project.id,
            source_type="slack_message",
            external_id=f"hist-{suffix}",
            title="Old thread: Deprecated retry worker prototype",
            author="Alice Smith",
            content="Deprecated prototype before migrating payment webhook retries to RabbitMQ dead-letter queue.",
            sha256_hash="hist1",
            source_timestamp=old_ts,
        )
        db.add(historical_rec)
        db.commit()

        drift1 = scan_project_for_drift(db, project.id, actor_user_id=user.id)
        db.refresh(claim)
        assert claim.verification_status == "Verified by Reviewer"
        assert drift1["detected"] == 0

        # 2. Newer post-claim source reporting migration/replacement MUST trigger drift & invalidate claim
        newer_rec = SourceRecord(
            integration_id=integ.id,
            project_id=project.id,
            source_type="github_pr",
            external_id=f"new-{suffix}",
            title="PR #204: Replaced RabbitMQ dead-letter queue webhook retries with SQS FIFO",
            author="Bob Chen",
            content="Deprecated RabbitMQ dead-letter queue and migrated all payment webhook retries workers to AWS SQS FIFO.",
            sha256_hash="new1",
            source_timestamp=new_ts,
        )
        db.add(newer_rec)
        db.commit()

        drift2 = scan_project_for_drift(db, project.id, actor_user_id=user.id)
        db.refresh(claim)
        db.refresh(ho)
        assert drift2["detected"] >= 1
        assert claim.verification_status == "Contradicted"
        assert (ho.reconstruction_stats or {}).get("has_drift_warning") is True
        assert (ho.reconstruction_stats or {}).get("drift_invalidated_claims", 0) >= 1
    finally:
        if org is not None:
            _cleanup(db, org.id)
        db.close()
