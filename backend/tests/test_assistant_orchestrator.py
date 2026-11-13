from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, init_db
from app.core.security import encrypt_credentials
from app.main import app
from app.models.evidence import Evidence
from app.models.integration import Integration, SourceRecord
from app.models.knowledge import Decision, KnowledgeEntity, RiskItem, TaskItem
from app.models.workspace import Organization, Project, User
from app.services.assistant.intent_classifier import (
    INTENT_ANALYTICAL,
    INTENT_CROSS_SOURCE,
    INTENT_DATA_RETRIEVAL,
    INTENT_DIRECT_METRIC,
    INTENT_HANDOVER,
    INTENT_SEMANTIC_RAG,
    IntentClassifier,
)
from app.services.assistant.orchestrator import query_orchestrator
from app.services.assistant.tools import (
    get_connected_integrations,
    get_github_repository_inventory,
    get_project_decisions,
    get_project_risks,
    get_project_tasks,
    get_repository_commits,
    get_repository_contributors,
)

init_db()
client = TestClient(app)


def _register_user(prefix: str = "orch"):
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@obsidian-assistant.io"
    res = client.post(
        "/api/v1/auth/register",
        json={
            "name": f"{prefix.title()} Engineer",
            "email": email,
            "password": "ObsidianSecurePassword2026!",
            "role": "tech_lead",
            "title": "Lead Architect",
            "department": "Engineering",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    return {
        "email": email,
        "token": data["access_token"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
        "project_id": data["active_project_id"],
        "user_id": data["user"]["id"],
    }


def _seed_project_data(db: Session, project_id: str, user_id: str):
    # 1. GitHub Integration
    integ = Integration(
        project_id=project_id,
        user_id=user_id,
        provider="github",
        name="GitHub Integration",
        status="connected",
        connected_account="obsidian-lead",
        credentials=encrypt_credentials({"access_token": "gho_mocktoken123"}),
        config={"repos": ["obsidian-lead/Trustify", "obsidian-lead/core-api", "obsidian-lead/docs-private"]},
        items_synced=12,
    )
    db.add(integ)
    db.flush()

    # 2. SourceRecords
    c1 = "Decentralized identity verification platform using Next.js and FastAPI."
    sr1 = SourceRecord(
        project_id=project_id,
        integration_id=integ.id,
        source_type="github_repository",
        external_id="repo-1",
        title="obsidian-lead/Trustify",
        content=c1,
        author="obsidian-lead",
        metadata_json={"repository": "obsidian-lead/Trustify", "private": False, "default_branch": "main"},
        sha256_hash=hashlib.sha256(c1.encode()).hexdigest(),
    )
    c2 = "Core API microservice with pgvector integration."
    sr2 = SourceRecord(
        project_id=project_id,
        integration_id=integ.id,
        source_type="github_repository",
        external_id="repo-2",
        title="obsidian-lead/core-api",
        content=c2,
        author="obsidian-lead",
        metadata_json={"repository": "obsidian-lead/core-api", "private": False, "default_branch": "main"},
        sha256_hash=hashlib.sha256(c2.encode()).hexdigest(),
    )
    c3 = "Confidential architectural specifications."
    sr3 = SourceRecord(
        project_id=project_id,
        integration_id=integ.id,
        source_type="github_repository",
        external_id="repo-3",
        title="obsidian-lead/docs-private",
        content=c3,
        author="obsidian-lead",
        metadata_json={"repository": "obsidian-lead/docs-private", "private": True, "default_branch": "main"},
        sha256_hash=hashlib.sha256(c3.encode()).hexdigest(),
    )
    # Commit record
    c_commit = "Added Row Level Security check to Supabase connectors."
    sr_commit = SourceRecord(
        project_id=project_id,
        integration_id=integ.id,
        source_type="github_commit",
        external_id="sha-abcdef123456",
        title="feat(auth): add multi-tenant rls checks",
        content=c_commit,
        author="obsidian-lead",
        metadata_json={"sha": "abcdef12", "repository": "obsidian-lead/Trustify"},
        sha256_hash=hashlib.sha256(c_commit.encode()).hexdigest(),
    )
    # Slack discussion record
    c_slack = "Agreed in #architecture to enforce row-level security across all tenant queries."
    sr_slack = SourceRecord(
        project_id=project_id,
        integration_id=integ.id,
        source_type="slack_message",
        external_id="slack-msg-99",
        title="#architecture: Database isolation policy",
        content=c_slack,
        author="sarah.architect",
        sha256_hash=hashlib.sha256(c_slack.encode()).hexdigest(),
    )
    db.add_all([sr1, sr2, sr3, sr_commit, sr_slack])

    # 3. Knowledge Entities (Contributors)
    ke1 = KnowledgeEntity(
        project_id=project_id,
        name="Sarah Chen",
        entity_type="Person",
        description="Top contributor to obsidian-lead/Trustify maintaining authentication pipelines.",
    )
    ke2 = KnowledgeEntity(
        project_id=project_id,
        name="Alex Rivera",
        entity_type="Person",
        description="Core contributor to obsidian-lead/core-api maintaining data connectors.",
    )
    db.add_all([ke1, ke2])

    # 4. Tasks
    t1 = TaskItem(
        project_id=project_id,
        title="Migrate database migrations to Supabase branch",
        owner="Sarah Chen",
        priority="high",
        status="open",
    )
    t2 = TaskItem(
        project_id=project_id,
        title="Complete E2E integration test suite",
        owner="Alex Rivera",
        priority="normal",
        status="open",
    )
    db.add_all([t1, t2])

    # 5. Decisions
    d1 = Decision(
        project_id=project_id,
        title="ADR-001: Centralized AI Inference with Groq & Gemini Fallback",
        summary="Use Groq Llama 3.3 for high-throughput extraction with deterministic fallback.",
        reasoning="High throughput extraction and strict tenant privacy.",
        decision_maker="Lead Architect",
        date="2026-11-13",
    )
    db.add(d1)

    # 6. Risks
    r1 = RiskItem(
        project_id=project_id,
        title="Single point of failure on legacy payment webhook",
        description="Legacy webhook endpoint lacks replay protection and idempotent execution.",
        severity="critical",
        likelihood="medium",
        owner="Sarah Chen",
        mitigation_strategy="Implement idempotent ledger transactions with nonce checks.",
    )
    db.add(r1)

    db.commit()


# =============================================================================
# 1. Intent Classification Tests (All 14 Required Questions)
# =============================================================================

def test_intent_classification_all_14_questions():
    # 1. Simple factual: How many repositories do I have?
    i1 = IntentClassifier.classify("how many repo are there in my github")
    assert i1.category == INTENT_DIRECT_METRIC
    assert i1.target_entity == "github_repos"
    assert i1.action == "count"

    # 2. How many are private?
    i2 = IntentClassifier.classify("how many are private?")
    assert i2.category == INTENT_DIRECT_METRIC
    assert i2.target_entity == "github_repos"
    assert i2.filter_params.get("visibility") == "private"

    # 3. How many are public?
    i3 = IntentClassifier.classify("how many are public?")
    assert i3.category == INTENT_DIRECT_METRIC
    assert i3.target_entity == "github_repos"
    assert i3.filter_params.get("visibility") == "public"

    # 4. Data retrieval: Show all my repositories
    i4 = IntentClassifier.classify("Show all my repositories.")
    assert i4.category == INTENT_DATA_RETRIEVAL
    assert i4.target_entity == "github_repos"
    assert i4.action == "list"

    # 5. Which repository was updated most recently?
    i5 = IntentClassifier.classify("Which repository was updated most recently?")
    assert i5.category == INTENT_DATA_RETRIEVAL
    assert i5.target_entity == "github_repos"
    assert i5.action == "recent"

    # 6. Which repository has the most contributors?
    i6 = IntentClassifier.classify("Which repository has the most contributors?")
    assert i6.category == INTENT_DATA_RETRIEVAL
    assert i6.target_entity == "github_repos"
    assert i6.action == "most_contributors"

    # 7. Who contributes to Trustify?
    i7 = IntentClassifier.classify("Who contributes to Trustify?")
    assert i7.category == INTENT_DATA_RETRIEVAL
    assert i7.target_entity == "github_contributors"
    assert i7.specific_resource == "Trustify"

    # 8. Analytical: What technologies does Trustify use?
    i8 = IntentClassifier.classify("What technologies does Trustify use?")
    assert i8.category == INTENT_ANALYTICAL
    assert i8.target_entity == "repo_technologies"
    assert i8.specific_resource == "Trustify"

    # 9. What are the latest commits?
    i9 = IntentClassifier.classify("What are the latest commits?")
    assert i9.category == INTENT_DATA_RETRIEVAL
    assert i9.target_entity == "github_commits"
    assert i9.action == "commits"

    # 10. Cross-source: What did we decide in Slack?
    i10 = IntentClassifier.classify("What did we decide in Slack?")
    assert i10.category == INTENT_CROSS_SOURCE
    assert i10.target_entity == "slack_discussions"

    # 11. What tasks are unfinished?
    i11 = IntentClassifier.classify("What tasks are unfinished?")
    assert i11.category == INTENT_DATA_RETRIEVAL
    assert i11.target_entity == "tasks"

    # 12. Analyse my repository architecture
    i12 = IntentClassifier.classify("Analyse my repository architecture.")
    assert i12.category == INTENT_ANALYTICAL
    assert i12.target_entity == "architecture"

    # 13. What are the biggest project risks?
    i13 = IntentClassifier.classify("What are the biggest project risks?")
    assert i13.category == INTENT_ANALYTICAL
    assert i13.target_entity == "risks"

    # 14. Handover: Generate a complete project handover
    i14 = IntentClassifier.classify("Generate a complete project handover.")
    assert i14.category == INTENT_HANDOVER


def test_conversational_follow_up_resolution():
    history = [
        {"role": "user", "content": "Tell me about obsidian-lead/Trustify"},
        {"role": "assistant", "content": "Trustify is the identity verification repo."},
    ]
    follow_up = IntentClassifier.classify("Who contributes to it?", conversation_history=history)
    assert follow_up.target_entity == "github_contributors"
    assert "Trustify" in (follow_up.specific_resource or "")


# =============================================================================
# 2. Backend Tools & Programmatic Calculation Tests
# =============================================================================

def test_repository_inventory_calculation():
    user_info = _register_user(prefix="invtest")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_info["user_id"]).first()
        _seed_project_data(db, user_info["project_id"], user.id)

        inv = get_github_repository_inventory(user, user_info["project_id"], db)
        assert inv["status"] == "connected"
        assert inv["total"] == 3
        assert inv["public"] == 2
        assert inv["private"] == 1
        assert len(inv["repositories"]) == 3
    finally:
        db.close()


def test_disconnected_github_inventory_graceful_handling():
    user_info = _register_user(prefix="disctest")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_info["user_id"]).first()
        # No integration seeded
        inv = get_github_repository_inventory(user, user_info["project_id"], db)
        assert inv["status"] == "not_connected"
        assert inv["total"] == 0
        assert "not connected" in inv["message"].lower()
    finally:
        db.close()


def test_contributors_and_commits_tools():
    user_info = _register_user(prefix="tools")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_info["user_id"]).first()
        _seed_project_data(db, user_info["project_id"], user.id)

        # Contributors
        c_res = get_repository_contributors(user, user_info["project_id"], "Trustify", db)
        assert c_res["total"] >= 1
        assert any("Sarah Chen" in c["name"] for c in c_res["contributors"])

        # Commits
        commits = get_repository_commits(user, user_info["project_id"], limit=5, db=db)
        assert commits["total"] >= 1
        assert "feat(auth)" in commits["commits"][0]["title"]
    finally:
        db.close()


def test_tasks_and_risks_tools():
    user_info = _register_user(prefix="tasksrisk")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_info["user_id"]).first()
        _seed_project_data(db, user_info["project_id"], user.id)

        # Tasks
        tasks = get_project_tasks(user, user_info["project_id"], db)
        assert tasks["total"] == 2

        # Decisions
        decs = get_project_decisions(user, user_info["project_id"], db)
        assert decs["total"] == 1
        assert "ADR-001" in decs["decisions"][0]["title"]

        # Risks
        risks = get_project_risks(user, user_info["project_id"], db)
        assert risks["total"] == 1
        assert "payment webhook" in risks["risks"][0]["title"]
    finally:
        db.close()


# =============================================================================
# 3. End-to-End API Tests (Query Orchestration & Model Anonymization)
# =============================================================================

def test_e2e_simple_repo_count_level_1():
    user_info = _register_user(prefix="e2ecount")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_info["user_id"]).first()
        _seed_project_data(db, user_info["project_id"], user.id)

        res = client.post(
            "/api/v1/assistant/query",
            json={
                "project_id": user_info["project_id"],
                "question": "how many repo are there in my github",
            },
            headers=user_info["headers"],
        )
        assert res.status_code == 200, res.text
        data = res.json()

        # Level 1 presentation verification
        assert "**3 GitHub repositories**" in data["answer"]
        assert "**Public**: 2" in data["answer"]
        assert "**Private**: 1" in data["answer"]
        assert data["confidence"] == 1.0
        assert data["is_grounded"] is True
        assert data["response_level"] == 1

        # Model used must NOT leak raw technical jargon or fallback messages
        assert data["model_used"] == "Obsidian Intelligence Engine"
        assert "Extractive Synthesis" not in data["model_used"]
        assert "extractive fallback active while live LLM quota resets" not in data["answer"]

        # Lightweight single citation
        assert len(data["citations"]) == 1
        assert data["citations"][0]["source_type"] == "GITHUB_INTEGRATION"
    finally:
        db.close()


def test_e2e_repo_list_level_2():
    user_info = _register_user(prefix="e2elist")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_info["user_id"]).first()
        _seed_project_data(db, user_info["project_id"], user.id)

        res = client.post(
            "/api/v1/assistant/query",
            json={
                "project_id": user_info["project_id"],
                "question": "Show all my repositories.",
            },
            headers=user_info["headers"],
        )
        assert res.status_code == 200, res.text
        data = res.json()

        assert "Connected GitHub Repositories" in data["answer"]
        assert "Trustify" in data["answer"]
        assert data["response_level"] == 2
        assert data["model_used"] == "Obsidian Intelligence Engine"
    finally:
        db.close()


def test_e2e_architecture_analysis_level_3():
    user_info = _register_user(prefix="e2earch")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_info["user_id"]).first()
        _seed_project_data(db, user_info["project_id"], user.id)

        res = client.post(
            "/api/v1/assistant/query",
            json={
                "project_id": user_info["project_id"],
                "question": "Analyse my repository architecture.",
            },
            headers=user_info["headers"],
        )
        assert res.status_code == 200, res.text
        data = res.json()

        assert "Architectural Topology & Analysis" in data["answer"]
        assert "Executive Summary" in data["answer"]
        assert data["response_level"] == 3
        assert data["confidence"] >= 0.9
        assert data["model_used"] == "Obsidian Intelligence Engine"
    finally:
        db.close()


def test_e2e_handover_report():
    user_info = _register_user(prefix="e2ehand")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_info["user_id"]).first()
        _seed_project_data(db, user_info["project_id"], user.id)

        res = client.post(
            "/api/v1/assistant/query",
            json={
                "project_id": user_info["project_id"],
                "question": "Generate a complete project handover.",
            },
            headers=user_info["headers"],
        )
        assert res.status_code == 200, res.text
        data = res.json()

        assert "Project Handover Readiness Report" in data["answer"]
        assert "Incoming Developer Critical Checklist" in data["answer"]
        assert data["response_level"] == 3
    finally:
        db.close()


def test_multi_tenant_isolation_on_assistant():
    alice = _register_user(prefix="alice")
    bob = _register_user(prefix="bob")

    # Bob tries to query Alice's project
    res = client.post(
        "/api/v1/assistant/query",
        json={
            "project_id": alice["project_id"],
            "question": "how many repo are there in my github",
        },
        headers=bob["headers"],
    )
    # Must be 403 Forbidden
    assert res.status_code == 403
