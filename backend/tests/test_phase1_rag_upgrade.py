"""Phase 1 verification tests: Lossless chunking, Multi-Lang AST, Asymmetric Embeddings & Graph-RAG."""

from datetime import datetime, timezone
import hashlib
import uuid

from app.core.database import SessionLocal, init_db
from app.models.evidence import Evidence
from app.models.integration import Integration, SourceRecord
from app.models.knowledge import (
    Decision,
    EmbeddingRecord,
    KnowledgeEntity,
    KnowledgeRelationship,
    RiskItem,
)
from app.models.workspace import Organization, Project, User, Workspace
from app.services.ai_engine import ai_engine
from app.services.code_ast_indexer import (
    build_repo_web_url,
    parse_go_source,
    parse_java_source,
    parse_rust_source,
    persist_ast_graph_facts,
    summarize_repository_ast,
)
from app.services.ingestion_service import chunk_structured_content, upsert_source_records
from app.services.retrieval_service import retrieve_hybrid_graph_context


def _seed_project(db, suffix: str):
    org = Organization(name=f"Org-{suffix}", slug=f"org-{suffix}")
    db.add(org)
    db.flush()
    user = User(
        org_id=org.id,
        email=f"u-{suffix}@example.com",
        password_hash="x",
        name="Test Engineer",
        role="tech_lead",
        is_active=True,
    )
    db.add(user)
    db.flush()
    ws = Workspace(
        org_id=org.id,
        name=f"WS-{suffix}",
        slug=f"ws-{suffix}",
        owner_id=user.id,
    )
    db.add(ws)
    db.flush()
    project = Project(
        workspace_id=ws.id,
        creator_id=user.id,
        name=f"Proj-{suffix}",
        slug=f"proj-{suffix}",
        description="Phase 1 RAG test project",
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


def _cleanup_project(db, org_id: str):
    db.rollback()
    ws_ids = [w.id for w in db.query(Workspace).filter(Workspace.org_id == org_id).all()]
    proj_ids = [p.id for p in db.query(Project).filter(Project.workspace_id.in_(ws_ids)).all()] if ws_ids else []
    for pid in proj_ids:
        db.query(EmbeddingRecord).filter(EmbeddingRecord.project_id == pid).delete(synchronize_session=False)
        db.query(KnowledgeRelationship).filter(KnowledgeRelationship.project_id == pid).delete(synchronize_session=False)
        db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == pid).delete(synchronize_session=False)
        db.query(Decision).filter(Decision.project_id == pid).delete(synchronize_session=False)
        db.query(RiskItem).filter(RiskItem.project_id == pid).delete(synchronize_session=False)
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


def test_lossless_hierarchical_chunking_and_pruning():
    init_db()
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    org = None
    try:
        org, _, project, integ = _seed_project(db, suffix)
        long_sections = [
            f"## Section {idx}: Circuit Breaker Config\n"
            + (f"Latency threshold for billing service shard {idx} is {100 + idx}ms with retry backoff.\n" * 18)
            for idx in range(1, 5)
        ]
        long_body = "\n\n".join(long_sections)
        assert len(long_body) > 3200

        chunks = chunk_structured_content(long_body, source_type="confluence", target_chars=1200, overlap_chars=180)
        assert len(chunks) >= 3

        raw_record = {
            "source_type": "confluence",
            "external_id": f"conf-{suffix}",
            "title": "Billing Circuit Breaker Architecture",
            "content": long_body,
            "sha256": hashlib.sha256(long_body.encode("utf-8")).hexdigest(),
            "author": "alice@acme.io",
            "url": "https://acme.atlassian.net/wiki/spaces/ENG/pages/1",
            "metadata": {},
        }
        upsert_source_records(db, integ, [raw_record])
        db.commit()

        evidences = (
            db.query(Evidence)
            .filter(Evidence.project_id == project.id)
            .order_by(Evidence.chunk_index.asc())
            .all()
        )
        assert len(evidences) >= 3
        parent = evidences[0]
        assert parent.parent_evidence_id is None
        assert parent.total_chunks == len(evidences)
        assert parent.full_text is not None and len(parent.full_text) >= 200
        for idx, child in enumerate(evidences[1:], start=1):
            assert child.parent_evidence_id == parent.id
            assert child.chunk_index == idx

        emb_rows = db.query(EmbeddingRecord).filter(EmbeddingRecord.project_id == project.id).all()
        assert len(emb_rows) == len(evidences)
        assert all(er.task_type == "RETRIEVAL_DOCUMENT" for er in emb_rows)

        # Update with short body and verify trailing chunks + embeddings are pruned cleanly
        short_body = "Short updated summary for billing breaker."
        raw_record_short = dict(
            raw_record,
            content=short_body,
            sha256=hashlib.sha256(short_body.encode("utf-8")).hexdigest(),
        )
        upsert_source_records(db, integ, [raw_record_short])
        db.commit()

        evidences_after = db.query(Evidence).filter(Evidence.project_id == project.id).all()
        emb_after = db.query(EmbeddingRecord).filter(EmbeddingRecord.project_id == project.id).all()
        assert len(evidences_after) == 1
        assert len(emb_after) == 1
        assert evidences_after[0].total_chunks == 1
    finally:
        if org is not None:
            _cleanup_project(db, org.id)
        else:
            db.rollback()
        db.close()


def test_multilang_ast_gitlab_urls_and_unlimited_symbols():
    init_db()
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    org = None
    try:
        org, _, project, _ = _seed_project(db, suffix)
        # GitLab tree/blob URL check
        gl_tree = build_repo_web_url("gitlab", "https://gitlab.example.com", "core/payments", "main")
        gl_blob = build_repo_web_url("gitlab", "https://gitlab.example.com", "core/payments", "main", "cmd/server/main.go")
        assert "/-/tree/main" in gl_tree
        assert "/-/blob/main/cmd/server/main.go" in gl_blob

        go_parsed = parse_go_source(
            "cmd/server/main.go",
            'package main\nimport "net/http"\ntype LedgerRouter struct {}\nfunc StartLedgerServer(cfg string) {}\n',
        )
        assert "LedgerRouter" in go_parsed["classes"]
        assert "StartLedgerServer" in go_parsed["functions"]

        rust_parsed = parse_rust_source(
            "src/lib.rs",
            "pub struct TokenVault {}\nfn verify_hmac_sig(key: &str) -> bool { true }\n",
        )
        assert "TokenVault" in rust_parsed["classes"]
        assert "verify_hmac_sig" in rust_parsed["functions"]

        java_parsed = parse_java_source(
            "src/BillingEngine.java",
            "package com.acme;\npublic class BillingEngine {\n  public void reconcileInvoice(String id) {}\n}\n",
        )
        assert "BillingEngine" in java_parsed["classes"]
        assert "reconcileInvoice" in java_parsed["functions"]

        deps_list = ",\n".join([f'"dep-pkg-{i}": "^1.0.{i}"' for i in range(22)])
        files = [
            {"path": "package.json", "content": '{"name": "core-svc", "dependencies": {' + deps_list + "}}"},
            {"path": "cmd/server/main.go", "content": 'package main\ntype LedgerRouter struct {}\nfunc StartLedgerServer() {}\n'},
            {"path": "src/lib.rs", "content": "pub struct TokenVault {}\nfn verify_hmac_sig() {}\n"},
        ]
        summary = summarize_repository_ast(
            owner_repo="core/payments",
            branch="main",
            files=files,
            tree_paths=["package.json", "cmd/server/main.go", "src/lib.rs"],
            source_type="gitlab_ast",
            repo_base_url="https://gitlab.example.com",
        )
        assert "/-/tree/main" in summary["records"][0]["url"]
        assert len(summary["records"]) >= 2  # parent architecture + module chunks

        created = persist_ast_graph_facts(db, project.id, "core/payments", summary)
        db.commit()
        assert created > 15  # confirms 15-package hardcoded gate is gone

        entities = db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == project.id).all()
        names = {e.name for e in entities}
        assert "dep-pkg-20" in names
    finally:
        if org is not None:
            _cleanup_project(db, org.id)
        else:
            db.rollback()
        db.close()


def test_asymmetric_task_type_and_citation_guard():
    doc_vec = ai_engine.generate_embedding(
        "Redis Sentinel failover quorum timeout",
        task_type="RETRIEVAL_DOCUMENT",
        title="Cache ADR",
    )
    qry_vec = ai_engine.generate_embedding(
        "How does Redis failover work?",
        task_type="RETRIEVAL_QUERY",
    )
    assert len(doc_vec) == len(qry_vec)
    assert any(v != 0.0 for v in doc_vec)

    orig_get_client = ai_engine._get_client
    ai_engine._get_client = lambda: None
    try:
        resp = ai_engine.answer_question(
            question="How does Redis failover work?",
            context_docs=[
                {
                    "id": "ev-1",
                    "entity_type": "evidence",
                    "source_type": "confluence",
                    "source_title": "Cache ADR",
                    "excerpt": "Redis Sentinel manages failover with a 5s quorum timeout.",
                    "full_context": "Redis Sentinel manages failover with a 5s quorum timeout across 3 sentinel nodes.",
                    "confidence": 0.9,
                }
            ],
        )
        assert resp["is_grounded"] is True
        assert "[Evidence 99]" not in resp["answer"]
        assert len(resp["citations"]) == 1
    finally:
        ai_engine._get_client = orig_get_client


def test_multi_entity_graph_rag_retrieval_and_abstain():
    init_db()
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    org = None
    try:
        org, _, project, _ = _seed_project(db, suffix)
        # Even with ZERO Evidence rows, Decisions + KnowledgeGraph should be retrieved
        dec = Decision(
            project_id=project.id,
            title="Adopt ClickHouse for Event Telemetry",
            summary="Replaced PostgreSQL time-series partitioning with ClickHouse cluster.",
            reasoning="PostgreSQL vacuum stalled under 50k writes/sec.",
            decision_maker="Priya Nair",
            date=datetime.now(timezone.utc),
            component="telemetry-pipeline",
            confidence=0.92,
            evidence_ids=[],
        )
        risk = RiskItem(
            project_id=project.id,
            title="ClickHouse ZooKeeper Quorum Single Node",
            description="Only one ZooKeeper node exists in staging.",
            category="infrastructure",
            severity="high",
            likelihood="medium",
            owner="Priya Nair",
            related_components=["telemetry-pipeline"],
            evidence_ids=[],
        )
        e_svc = KnowledgeEntity(
            project_id=project.id,
            entity_type="component",
            name="telemetry-pipeline",
            description="High-volume ingestion stream writing to ClickHouse",
        )
        e_owner = KnowledgeEntity(
            project_id=project.id,
            entity_type="person",
            name="Priya Nair",
            description="Lead Architect for telemetry-pipeline",
        )
        db.add_all([dec, risk, e_svc, e_owner])
        db.flush()
        db.add(
            KnowledgeRelationship(
                project_id=project.id,
                source_entity_id=e_owner.id,
                target_entity_id=e_svc.id,
                relation_type="owns",
                context="Primary maintainer for ClickHouse telemetry ingestion",
            )
        )
        db.commit()

        docs = retrieve_hybrid_graph_context(
            project_id=project.id,
            question="Why did we switch telemetry-pipeline to ClickHouse and who owns it?",
            departing_focus="Priya Nair",
            db=db,
            all_evidences=[],
            top_k=6,
        )
        entity_types = {d.get("entity_type") for d in docs}
        assert "decision" in entity_types
        assert any("ClickHouse" in d.get("full_context", "") for d in docs)

        # Unrelated query should abstain cleanly (empty context)
        unrelated = retrieve_hybrid_graph_context(
            project_id=project.id,
            question="What temperature should I preheat an oven for sourdough bread?",
            departing_focus=None,
            db=db,
            all_evidences=[],
            top_k=6,
        )
        assert unrelated == []
    finally:
        if org is not None:
            _cleanup_project(db, org.id)
        else:
            db.rollback()
        db.close()
