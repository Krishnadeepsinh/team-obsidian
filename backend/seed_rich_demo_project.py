import sys
import os
import uuid
import hashlib
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.core.database import SessionLocal
from app.models.workspace import User, Project, ProjectMember, Workspace
from app.models.integration import Integration, IntegrationProjectAccess
try:
    from app.models.document import Document
except Exception:
    Document = None
from app.models.knowledge import (
    KnowledgeEntity,
    KnowledgeRelationship,
    Decision,
    RiskItem,
    KnowledgeGap,
    TaskItem,
    EmbeddingRecord,
)
from app.models.handover import (
    Handover,
    HandoverSection,
    HandoverApproval,
    ReadinessSimulation,
    ExitInterviewQuestion,
)
from app.models.evidence import Evidence
from app.core.security import encrypt_credentials
from app.core.config import settings

def run():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == 'team.obsidian44@gmail.com').first()
        if not user:
            print("ERROR: User team.obsidian44@gmail.com not found!")
            return

        print(f"Seeding rich project data for user {user.id} ({user.email})...")

        # 1. Update or create the primary project
        proj = db.query(Project).filter(
            (Project.creator_id == user.id) | (Project.workspace_id == user.personal_workspace_id)
        ).first()

        if not proj:
            proj = Project(
                id=str(uuid.uuid4()),
                workspace_id=user.personal_workspace_id,
                creator_id=user.id,
                name="TEAM OBSIDIAN: Enterprise Knowledge Transfer & Architecture Platform",
                slug="team-obsidian-core",
                description="Production knowledge reconstruction & handover intelligence system. Ingests source code ASTs, git commit graphs, Jira engineering tickets, Confluence ADRs, Notion operational runbooks, and Slack incident threads into a verifiable dependency graph with automated Single Point of Failure (SPOF) analysis and handover simulation.",
                priority="critical",
                status="active",
                tags=["architecture", "spof-detection", "ast-index", "enterprise-rag", "zero-trust", "handover-ready", "production"],
                is_demo=True,
                target_handover_date=datetime.now(timezone.utc) + timedelta(days=14),
                metadata_json={
                    "lead_architect": "Dr. Evelyn Reed (Departing)",
                    "incoming_architect": "Judge Evaluator (Demo)",
                    "architecture_style": "Event-Driven Microservices & Hybrid Graph-RAG",
                    "tier": "Tier-1 Production",
                    "readiness_score": 94.5,
                    "monitored_repos": ["teamobsidian44/Data", "team-obsidian-group/team-obsidian-project"],
                    "primary_database": "Supabase PostgreSQL 15 + pgvector",
                    "auth_broker": "Nango Enterprise Unified OAuth",
                }
            )
            db.add(proj)
            db.flush()
            print(f"Created project: {proj.name}")
        else:
            proj.name = "TEAM OBSIDIAN: Enterprise Knowledge Transfer & Architecture Platform"
            proj.slug = "team-obsidian-core"
            proj.description = "Production knowledge reconstruction & handover intelligence system. Ingests source code ASTs, git commit graphs, Jira engineering tickets, Confluence ADRs, Notion operational runbooks, and Slack incident threads into a verifiable dependency graph with automated Single Point of Failure (SPOF) analysis and handover simulation."
            proj.priority = "critical"
            proj.status = "active"
            proj.tags = ["architecture", "spof-detection", "ast-index", "enterprise-rag", "zero-trust", "handover-ready", "production"]
            proj.is_demo = True
            proj.target_handover_date = datetime.now(timezone.utc) + timedelta(days=14)
            proj.metadata_json = {
                "lead_architect": "Dr. Evelyn Reed (Departing)",
                "incoming_architect": "Judge Evaluator (Demo)",
                "architecture_style": "Event-Driven Microservices & Hybrid Graph-RAG",
                "tier": "Tier-1 Production",
                "readiness_score": 94.5,
                "monitored_repos": ["teamobsidian44/Data", "team-obsidian-group/team-obsidian-project"],
                "primary_database": "Supabase PostgreSQL 15 + pgvector",
                "auth_broker": "Nango Enterprise Unified OAuth",
            }
            print(f"Updated project: {proj.name}")

        now = datetime.now(timezone.utc)

        # 2. Seed Real Documents
        # Check if Document model exists in DB via raw SQL if model not in Python module
        docs_data = [
            {
                "id": str(uuid.uuid4()),
                "title": "TEAM_OBSIDIAN_SYSTEM_ARCHITECTURE_v2.md",
                "filename": "TEAM_OBSIDIAN_SYSTEM_ARCHITECTURE_v2.md",
                "file_type": "md",
                "mime_type": "text/markdown",
                "file_size_bytes": 14520,
                "status": "processed",
                "chunk_count": 8,
                "extracted_text": """# TEAM OBSIDIAN System Architecture & Services Specification v2.0

## 1. Executive Summary & Topology
TEAM OBSIDIAN is an enterprise-grade architectural reconstruction and knowledge handover platform. The system operates as an asynchronous pipeline that extracts code-level syntax trees (Python & TypeScript ASTs), git commit histories, pull requests, Slack discussions, Jira tickets, and Confluence wiki pages into an indexed dependency graph.

### Core Components:
1. **API Gateway & REST Router**: Built on FastAPI, providing zero-trust authentication, token-bucket rate limiting, and RFC-compliant webhook validation.
2. **Knowledge Extraction Engine**: Utilizes tree-sitter AST extractors for Python and TypeScript, decomposing source files into classes, functions, callers, callees, and imported modules.
3. **Graph Intelligence & SPOF Engine**: Identifies single points of failure (e.g., critical code modules modified solely by departing engineers), architecture drift, and circular dependencies.
4. **Unified Integrations Engine (Nango)**: Manages 8 external platforms (GitHub, GitLab, Jira Cloud, Confluence, Linear, Sentry, Slack, Notion) with token encryption at rest via AES-256-GCM.
5. **AI Reasoning & Dossier Synthesis**: Multi-engine hierarchy combining Google Gemini 3.5 Flash for grounded RAG synthesis and BAAI/bge-small-en-v1.5 embeddings with vector-cosine matching.

## 2. Microservice Boundaries & Data Flow
- **Client Tier**: Next.js 16 App Router web dashboard with Tailwind CSS, React Query, and Lucide UI components.
- **Persistence Tier**: Supabase PostgreSQL 15 with pgvector extension enabled, utilizing Row Level Security (RLS) and transaction poolers.
- **Worker Tier**: Celery / Redis asynchronous task queues executing heavy AST indexing and full-text vectorization.
""",
            },
            {
                "id": str(uuid.uuid4()),
                "title": "DISASTER_RECOVERY_AND_SPOF_PLAYBOOK.md",
                "filename": "DISASTER_RECOVERY_AND_SPOF_PLAYBOOK.md",
                "file_type": "md",
                "mime_type": "text/markdown",
                "file_size_bytes": 11840,
                "status": "processed",
                "chunk_count": 6,
                "extracted_text": """# Disaster Recovery, Failover & Key Rotation Playbook

## 1. High-Availability Database Failover
- **Primary Database**: `aws-0-ap-south-1.pooler.supabase.com:5432/postgres`
- **Failover Procedure**:
  1. Trigger standby promotion via Supabase CLI or management console.
  2. Verify connection string health via `/health` probe.
  3. Re-run Alembic schema verification (`python -m alembic upgrade head`).

## 2. External Credential & Nango Key Rotation
- **Rotation Frequency**: 90-day automated rotation cycle.
- **Emergency Invalidation Protocol**:
  1. If any PAT or Bot Token is leaked, execute immediate revocation in the provider developer console.
  2. Run `reconnect_integration` with the newly provisioned token.
  3. The backend automatically encrypts the new secret using `CREDENTIALS_ENCRYPTION_KEY` and updates the database row.

## 3. Circuit Breaker Rate Limit Recovery
- Rate limits are guarded by token buckets per user/IP.
- Sentry alerts trigger on HTTP 429 exhaustion (`Sentry-Obs-01`).
- Backoff policy uses exponential jitter (base 1.5s, max 30s).
""",
            },
            {
                "id": str(uuid.uuid4()),
                "title": "NANGO_UNIVERSAL_INTEGRATIONS_SPECIFICATION.md",
                "filename": "NANGO_UNIVERSAL_INTEGRATIONS_SPECIFICATION.md",
                "file_type": "md",
                "mime_type": "text/markdown",
                "file_size_bytes": 10240,
                "status": "processed",
                "chunk_count": 5,
                "extracted_text": """# Universal Integration Engine & Cross-Device Persistence Spec

## 1. Overview
TEAM OBSIDIAN delegates OAuth token acquisition to Nango while retaining strict server-side cryptographic ownership in Supabase PostgreSQL.

## 2. Supported Platforms
1. **GitHub**: Repo discovery, commit graphs, AST parsing (`teamobsidian44/Data`).
2. **Slack**: Channel message history, incident escalation (`#all-new-workspace`).
3. **Jira Cloud**: Epics, tickets, blocker threads (`KAN`, `SAM1`).
4. **Confluence**: Architecture wikis, ADR records (`OBS`).
5. **Linear**: Cycles, roadmap milestones (`TEA`).
6. **GitLab**: Merge requests, private group code (`team-obsidian-project`).
7. **Sentry**: Error telemetry, stack traces, release health (`team-obsidian`).
8. **Notion**: Runbooks, specifications, databases (`414735e0`).

## 3. Cross-Device Persistence
All credentials are bound to the authenticated user ID and project ID in PostgreSQL, never in browser LocalStorage or session cookies.
""",
            },
            {
                "id": str(uuid.uuid4()),
                "title": "ONBOARDING_WALKTHROUGH_FOR_INCOMING_LEAD.md",
                "filename": "ONBOARDING_WALKTHROUGH_FOR_INCOMING_LEAD.md",
                "file_type": "md",
                "mime_type": "text/markdown",
                "file_size_bytes": 8960,
                "status": "processed",
                "chunk_count": 4,
                "extracted_text": """# Incoming Lead Architect 14-Day Ramp-Up Guide

## Schedule & Milestones
- **Days 1–3**: Environment configuration, GitHub access (`teamobsidian44`), Slack channel joins (`#all-new-workspace`), Sentry alert review.
- **Days 4–7**: Knowledge Graph exploration, AST dependency review, ADR analysis (ADR-001 through ADR-005).
- **Days 8–10**: Shadowing the departing architect (Dr. Evelyn Reed) during live incident triage and PR review.
- **Days 11–14**: Exit interview completion, Handover Dossier formal sign-off, and primary on-call rotation transfer.
""",
            }
        ]

        from sqlalchemy import text
        # Insert documents using portable SQL
        for d in docs_data:
            existing_doc = db.execute(
                text("SELECT id FROM documents WHERE project_id = :pid AND title = :title"),
                {"pid": proj.id, "title": d["title"]}
            ).fetchone()
            if not existing_doc:
                db.execute(
                    text("""
                        INSERT INTO documents (
                            id, project_id, title, filename, file_type, file_size_bytes,
                            storage_path, sha256_hash, status, extracted_text, chunk_count,
                            uploaded_by, user_id, mime_type, created_at
                        ) VALUES (
                            :id, :project_id, :title, :filename, :file_type, :file_size_bytes,
                            :storage_path, :sha256_hash, :status, :extracted_text, :chunk_count,
                            :uploaded_by, :user_id, :mime_type, :created_at
                        )
                    """),
                    {
                        "id": d["id"],
                        "project_id": proj.id,
                        "title": d["title"],
                        "filename": d["filename"],
                        "file_type": d["file_type"],
                        "file_size_bytes": d["file_size_bytes"],
                        "storage_path": f"uploads/{proj.id}/{d['filename']}",
                        "sha256_hash": hashlib.sha256(d["extracted_text"].encode()).hexdigest(),
                        "status": d["status"],
                        "extracted_text": d["extracted_text"],
                        "chunk_count": d["chunk_count"],
                        "uploaded_by": user.email,
                        "user_id": user.id,
                        "mime_type": d["mime_type"],
                        "created_at": now,
                    }
                )
                print("Inserted document:", d["title"])

        # 3. Seed Knowledge Entities (Nodes in Knowledge Graph)
        entities_data = [
            ("FastAPI Async API Gateway", "service", "Core backend application routing authenticated REST and WebSocket traffic.", {"runtime": "Python 3.11", "port": 8000, "framework": "FastAPI"}),
            ("Next.js 16 Web Dashboard", "ui_component", "Modern responsive web dashboard rendering AST graphs, dossiers, and connector statuses.", {"framework": "Next.js 16", "bundler": "Turbopack"}),
            ("Supabase PostgreSQL (pgvector)", "database", "Primary relational store with pgvector extensions for semantic similarity search.", {"host": "aws-0-ap-south-1.pooler.supabase.com", "engine": "PostgreSQL 15"}),
            ("Nango Enterprise Auth Broker", "external_service", "Unified OAuth 2.0 and API token broker managing external credential lifecycles.", {"provider": "Nango", "status": "active"}),
            ("Gemini 3.5 Flash Reasoning Agent", "ai_engine", "High-efficiency LLM orchestrating grounded knowledge synthesis and question answering.", {"model": "gemini-3.5-flash", "provider": "Google GenAI"}),
            ("teamobsidian44/Data (GitHub Core)", "repository", "Primary code repository containing AST parser modules, schema definitions, and migration files.", {"owner": "teamobsidian44", "branch": "main"}),
            ("team-obsidian-project (GitLab Repo)", "repository", "Secondary engineering repository containing deployment pipelines and runner configurations.", {"owner": "team.obsidian44", "platform": "GitLab"}),
            ("Payment Webhook Verification Handler", "module", "Critical signature verification module processing external financial events.", {"risk_level": "SPOF", "owner": "Dr. Evelyn Reed"}),
            ("Circuit Breaker Rate Limiter", "security_boundary", "Token-bucket rate limiter guarding public endpoints against denial of service.", {"rate_limit": "120/min", "backoff": "exponential"}),
            ("KAN-1: Cross-Platform Knowledge Sync", "jira_issue", "Epic tracking end-to-end AST ingestion across GitHub, Slack, and Confluence.", {"project": "KAN", "status": "In Progress"}),
            ("KAN-2: Automated Handover Readiness Gate", "jira_issue", "Ticket implementing automated exit interview simulation and confidence scoring.", {"project": "KAN", "status": "Done"}),
            ("TEA-1: AST Dependency Reconstruction", "linear_task", "Milestone tracking parser coverage across Python and TypeScript codebases.", {"team": "TEA", "cycle": "Cycle 14"}),
            ("#all-new-workspace: Architecture Discussions", "slack_channel", "Slack communication channel recording architectural debates, incident logs, and postmortems.", {"channel": "all-new-workspace", "type": "public"}),
            ("OBS-ADR-004: Relational-Vector Graph Schema", "confluence_page", "Confluence documentation page outlining the hybrid relational-vector storage model.", {"space": "OBS", "status": "Approved"}),
            ("Notion Runbook: Incident Recovery Protocols", "notion_page", "Operational runbook specifying database failover and secret rotation procedures.", {"database_id": "414735e0", "verified": True}),
            ("Sentry Sentry-Obs-01: API Rate Limit Alert", "sentry_issue", "Active Sentry telemetry alert monitoring rate limit circuit breaker events.", {"org": "team-obsidian", "environment": "production"}),
        ]

        entity_objs = {}
        for name, etype, desc, props in entities_data:
            existing_ent = db.query(KnowledgeEntity).filter(
                KnowledgeEntity.project_id == proj.id,
                KnowledgeEntity.name == name
            ).first()
            if not existing_ent:
                ent = KnowledgeEntity(
                    id=str(uuid.uuid4()),
                    project_id=proj.id,
                    entity_type=etype,
                    name=name,
                    description=desc,
                    properties=props,
                    confidence=0.95,
                    verification_status="verified",
                    created_by_user_id=user.id,
                    created_at=now,
                    updated_at=now,
                )
                db.add(ent)
                db.flush()
                entity_objs[name] = ent
                print("Added Knowledge Entity:", name)
            else:
                existing_ent.description = desc
                existing_ent.properties = props
                existing_ent.verification_status = "verified"
                entity_objs[name] = existing_ent

        # 4. Seed Knowledge Relationships (Edges in Knowledge Graph)
        rels_data = [
            ("FastAPI Async API Gateway", "Supabase PostgreSQL (pgvector)", "depends_on", "Direct SQL query execution and vector embedding lookups"),
            ("Next.js 16 Web Dashboard", "FastAPI Async API Gateway", "calls_api", "REST endpoints for dossiers, graph visualizations, and auth"),
            ("FastAPI Async API Gateway", "Nango Enterprise Auth Broker", "authenticates_via", "Delegates OAuth session management and token refreshes"),
            ("Nango Enterprise Auth Broker", "teamobsidian44/Data (GitHub Core)", "ingests_from", "Pulls commits, PRs, and file contents via GitHub REST API"),
            ("FastAPI Async API Gateway", "Gemini 3.5 Flash Reasoning Agent", "queries", "Transfers context windows and vector retrieval chunks for grounded Q&A"),
            ("FastAPI Async API Gateway", "Payment Webhook Verification Handler", "manages_spof", "Critical module with isolated single-engineer deployment privileges"),
            ("FastAPI Async API Gateway", "Circuit Breaker Rate Limiter", "monitors", "Enforces request throttling and registers alerts in Sentry"),
            ("Circuit Breaker Rate Limiter", "Sentry Sentry-Obs-01: API Rate Limit Alert", "monitors", "Telemetry trigger on 429 threshold breaches"),
            ("KAN-1: Cross-Platform Knowledge Sync", "teamobsidian44/Data (GitHub Core)", "tracks", "Jira epic tracking repository code ingestion"),
            ("KAN-1: Cross-Platform Knowledge Sync", "OBS-ADR-004: Relational-Vector Graph Schema", "documents", "Confluence documentation verifying architecture schema"),
            ("TEA-1: AST Dependency Reconstruction", "FastAPI Async API Gateway", "tracks", "Linear cycle milestone for backend AST extractors"),
            ("#all-new-workspace: Architecture Discussions", "Payment Webhook Verification Handler", "discusses", "Slack incident discussion on payment signature validation"),
            ("Notion Runbook: Incident Recovery Protocols", "Supabase PostgreSQL (pgvector)", "mitigates", "Operational runbook for primary database failover"),
            ("team-obsidian-project (GitLab Repo)", "FastAPI Async API Gateway", "depends_on", "CI/CD runner deployment targets Render production API"),
        ]

        for s_name, t_name, rel_type, ctx in rels_data:
            s_ent = entity_objs.get(s_name)
            t_ent = entity_objs.get(t_name)
            if s_ent and t_ent:
                existing_rel = db.query(KnowledgeRelationship).filter(
                    KnowledgeRelationship.project_id == proj.id,
                    KnowledgeRelationship.source_entity_id == s_ent.id,
                    KnowledgeRelationship.target_entity_id == t_ent.id,
                    KnowledgeRelationship.relation_type == rel_type,
                ).first()
                if not existing_rel:
                    db.add(KnowledgeRelationship(
                        id=str(uuid.uuid4()),
                        project_id=proj.id,
                        source_entity_id=s_ent.id,
                        target_entity_id=t_ent.id,
                        relation_type=rel_type,
                        context=ctx,
                        confidence=0.92,
                        verification_status="verified",
                        created_at=now,
                    ))
                    print(f"Added Relation: {s_name} --[{rel_type}]--> {t_name}")

        # 5. Seed Comprehensive Architecture Decisions (ADRs)
        adrs_data = [
            {
                "title": "ADR-001: Distributed Task Queue Migration to BullMQ & Redis",
                "summary": "Heavy background AST extraction and graph analysis workloads require durable message acknowledgments and concurrency throttling.",
                "reasoning": "Migrate worker queue from in-memory threading to Redis-backed BullMQ with rate-limiting and dead-letter queues.",
                "decision_maker": "Dr. Evelyn Reed (Principal Architect)",
                "date": "2026-11-10",
                "component": "Queue Engine",
                "decision_type": "architectural",
                "status": "accepted",
                "alternatives": "In-memory multiprocessing, Celery with RabbitMQ",
                "tradeoffs": "Introduces Redis operational dependency in exchange for guaranteed message durability.",
                "risks": "Redis memory saturation under spike ingestion loads.",
            },
            {
                "title": "ADR-002: Dual Token JWT & Email OTP Verification Architecture",
                "summary": "Strict zero-trust authentication requirement with 5-minute single-use OTP codes sent via enterprise SMTP.",
                "reasoning": "Store SHA-256 hashed OTPs with explicit purpose separation (login_verification vs password_reset) and 5-attempt rate limits.",
                "decision_maker": "Dr. Evelyn Reed (Principal Architect)",
                "date": "2026-11-12",
                "component": "Auth Engine",
                "decision_type": "security",
                "status": "accepted",
                "alternatives": "Single-factor password auth, Magic links via third-party provider",
                "tradeoffs": "Requires 2 steps during login in exchange for preventing brute-force account takeovers.",
                "risks": "Mail delivery provider latency during high load.",
            },
            {
                "title": "ADR-003: Selection of Dual-Engine AI Hierarchy (Gemini 3.5 Flash + Flash-Lite)",
                "summary": "Cost and latency optimization for enterprise knowledge synthesis and Q&A.",
                "reasoning": "Route complex synthesis and graph evaluation to Gemini 3.5 Flash; route fast classification and tag extraction to Gemini 3.5 Flash-Lite.",
                "decision_maker": "Dr. Evelyn Reed (Principal Architect)",
                "date": "2026-11-13",
                "component": "AI Reasoning Engine",
                "decision_type": "architectural",
                "status": "accepted",
                "alternatives": "Anthropic Claude 3.5 Sonnet only, OpenAI GPT-4o only",
                "tradeoffs": "Multi-model orchestration complexity in exchange for 70% reduced inference costs and sub-second latency.",
                "risks": "Minor formatting divergence between primary and secondary LLM responses.",
            },
            {
                "title": "ADR-004: Zero-Trust External Authentication via Nango Token Encryption",
                "summary": "Secure OAuth token acquisition and cross-device persistence across 8 developer platforms.",
                "reasoning": "All access tokens, refresh tokens, and bot secrets are encrypted at rest using AES-256-GCM before database storage.",
                "decision_maker": "Dr. Evelyn Reed (Principal Architect)",
                "date": "2026-11-14",
                "component": "Integration Broker",
                "decision_type": "security",
                "status": "accepted",
                "alternatives": "Direct OAuth client integration for each provider, storing plain text in database",
                "tradeoffs": "Requires centralized encryption key management in exchange for total security against database leaks.",
                "risks": "Loss of encryption key renders stored tokens unrecoverable.",
            },
            {
                "title": "ADR-005: Hybrid Relational-Vector RAG with Extractive Fallback",
                "summary": "Guaranteed answer delivery during provider rate limits or vector service degraded performance.",
                "reasoning": "Combine pgvector HNSW cosine similarity search with relational SQL fallback and extractive rule matching.",
                "decision_maker": "Dr. Evelyn Reed (Principal Architect)",
                "date": "2026-11-15",
                "component": "RAG Intelligence",
                "decision_type": "architectural",
                "status": "accepted",
                "alternatives": "Pure vector search without fallback",
                "tradeoffs": "Dual indexing pipeline in exchange for zero-outage response SLA.",
                "risks": "Slightly higher CPU utilization during initial document chunking.",
            },
        ]

        for adr in adrs_data:
            existing_adr = db.query(Decision).filter(
                Decision.project_id == proj.id,
                Decision.title == adr["title"]
            ).first()
            if not existing_adr:
                db.add(Decision(project_id=proj.id, created_at=now, updated_at=now, **adr))
                print("Added Decision:", adr["title"])

        # 6. Seed Single Point of Failure (SPOF) Risks
        risks_data = [
            {
                "title": "SPOF Alert: Core Payment Webhook Handler owned solely by departing engineer",
                "description": "Only 1 active maintainer has commit and deployment privileges on the Stripe/PayPal webhook verification service.",
                "severity": "critical",
                "likelihood": "high",
                "category": "knowledge_loss",
                "impact": "Total disruption to payment processing if critical hotfix required after departure.",
                "mitigation_strategy": "Execute KT session, record walkthrough video, and document signature rotation protocols in Confluence and Notion.",
                "status": "open",
                "owner": "Dr. Evelyn Reed",
            },
            {
                "title": "Architecture Drift: Uncatalogued Redis Caching Layer in API Gateway",
                "description": "Detected in-memory caching logic in git history not reflected in the architecture wiki.",
                "severity": "medium",
                "likelihood": "medium",
                "category": "technical_debt",
                "impact": "Latency and inconsistency during horizontal scaling across multi-region deployments.",
                "mitigation_strategy": "Generate automated AST graph documentation and link to Jira ticket KAN-42.",
                "status": "in_progress",
                "owner": "Judge Evaluator",
            },
            {
                "title": "SPOF Alert: Primary Database Single-Region Dependency in ap-south-1",
                "description": "Database pooler located solely in Mumbai (ap-south-1) without cross-region read replicas.",
                "severity": "critical",
                "likelihood": "low",
                "category": "infrastructure",
                "impact": "Complete service downtime during AWS ap-south-1 regional outages.",
                "mitigation_strategy": "Deploy multi-region read replicas in eu-central-1 and us-east-1 via Supabase enterprise tier.",
                "status": "open",
                "owner": "Dr. Evelyn Reed",
            },
            {
                "title": "Risk: Third-Party OAuth Token Invalidation Cascade across Nango Integrations",
                "description": "Third-party platform policy shifts (e.g. Slack workspace admin consent) can invalidate active bot tokens.",
                "severity": "high",
                "likelihood": "medium",
                "category": "security",
                "impact": "Automated ingestion halted until administrator re-approves scopes.",
                "mitigation_strategy": "Proactive token health polling every 4 hours with automated Slack alert to DevOps on-call.",
                "status": "mitigated",
                "owner": "Judge Evaluator",
            },
            {
                "title": "Risk: Memory Saturation during Large Multi-File AST Extraction",
                "description": "Repositories with over 10,000 files can trigger OOM kills on standard Render 512MB free tier containers.",
                "severity": "medium",
                "likelihood": "high",
                "category": "performance",
                "impact": "Worker crashes and delayed indexing cycles.",
                "mitigation_strategy": "Implemented batch chunking of 200 files per worker process with garbage collection invocations.",
                "status": "resolved",
                "owner": "Dr. Evelyn Reed",
            },
        ]

        for r in risks_data:
            existing_r = db.query(RiskItem).filter(
                RiskItem.project_id == proj.id,
                RiskItem.title == r["title"]
            ).first()
            if not existing_r:
                db.add(RiskItem(project_id=proj.id, created_at=now, **r))
                print("Added Risk:", r["title"])

        # 7. Seed Knowledge Gaps
        gaps_data = [
            {
                "title": "GAP-01: HMAC Webhook Secret Rotation Runbook Verification",
                "description": "No documented runbook exists for zero-downtime rotation of HMAC secret keys for Slack and GitLab incoming events.",
                "gap_type": "operational",
                "severity": "high",
                "impact": "Incoming webhooks may drop during secret rotation if dual-secret verification is not supported.",
                "recommended_action": "Implement dual-key grace window in app/api/v1/webhooks.py and document in Notion.",
                "status": "in_progress",
                "priority": "P1",
            },
            {
                "title": "GAP-02: AST Parser Scope for Asynchronous Python Generators",
                "description": "Tree-sitter parser misses yielded dependencies in async generator functions, creating minor graph gaps.",
                "gap_type": "technical",
                "severity": "medium",
                "impact": "Incomplete call graph for streaming endpoints.",
                "recommended_action": "Extend TreeSitter AST visitor in app/services/code_ast_indexer.py to capture Yield expressions.",
                "status": "open",
                "priority": "P2",
            },
            {
                "title": "GAP-03: Multi-tenant RLS Isolation Verification in Supabase",
                "description": "Comprehensive automated penetration test required to verify that cross-tenant project IDs cannot be read by unauthorized users.",
                "gap_type": "security",
                "severity": "high",
                "impact": "Potential data leakage between client workspaces.",
                "recommended_action": "Run test_security_pentest.py in CI and enforce app.current_user_id GUC on all pooler connections.",
                "status": "resolved",
                "priority": "P1",
            },
            {
                "title": "GAP-04: Atlassian Cloud 3LO Token Auto-Refresh Failure Mode",
                "description": "Atlassian OAuth tokens expire after 3600 seconds; refresh flow needs explicit fallback to Basic Auth when offline.",
                "gap_type": "architecture",
                "severity": "medium",
                "impact": "Temporary 401 errors during Jira project sync.",
                "recommended_action": "Bind verified Jira API token with email fallback directly in integration credentials.",
                "status": "resolved",
                "priority": "P2",
            },
            {
                "title": "GAP-05: Cold-Start Latency on Secondary LLM Fallback",
                "description": "When primary Gemini 3.5 Flash model encounters rate limits (HTTP 429), switching to Flash-Lite adds 400ms jitter.",
                "gap_type": "performance",
                "severity": "low",
                "impact": "Slight delay for user chat queries during peak hours.",
                "recommended_action": "Pre-warm secondary client connection pools in app/services/ai_engine.py.",
                "status": "in_progress",
                "priority": "P3",
            },
        ]

        for g in gaps_data:
            existing_g = db.query(KnowledgeGap).filter(
                KnowledgeGap.project_id == proj.id,
                KnowledgeGap.title == g["title"]
            ).first()
            if not existing_g:
                db.add(KnowledgeGap(project_id=proj.id, created_at=now, **g))
                print("Added Knowledge Gap:", g["title"])

        # 8. Seed Handover Tasks
        tasks_data = [
            ("Review System Architecture & AST Dependency Graph", "Inspect all 16 knowledge entities and verify caller/callee links.", "Judge Evaluator", "P1", "completed", now - timedelta(days=2)),
            ("Verify all 8 live platform connectors", "Ensure GitHub, Jira, Confluence, Linear, GitLab, Sentry, Slack, and Notion return 200 OK.", "Judge Evaluator", "P1", "completed", now - timedelta(days=1)),
            ("Execute Disaster Recovery & Key Rotation Runbook", "Simulate database failover and test AES-256 token decryption.", "Dr. Evelyn Reed", "P1", "in_progress", now + timedelta(days=3)),
            ("Validate Gemini 3.5 Flash Grounded Q&A against Checkout API questions", "Confirm zero hallucinations and 100% cited source evidence.", "Judge Evaluator", "P2", "completed", now - timedelta(days=1)),
            ("Configure Prometheus/Grafana SLA alerts on Render API", "Set up p99 latency thresholds and error rate monitors.", "DevOps Team", "P2", "pending", now + timedelta(days=5)),
            ("Simulate Readiness Score with Exit Interview Questions", "Complete simulated interview scenarios and verify score >= 90%.", "Judge Evaluator", "P1", "in_progress", now + timedelta(days=2)),
            ("Sign-off on Handover Dossier v2.0", "Formal verification and signature from Principal Architect and Lead Evaluator.", "Dr. Evelyn Reed", "P1", "pending", now + timedelta(days=7)),
            ("Transfer Admin Credentials in Atlassian & Sentry", "Transfer ownership of teamobsidian44 Atlassian site and team-obsidian Sentry org.", "Dr. Evelyn Reed", "P2", "pending", now + timedelta(days=10)),
        ]

        for t_title, t_desc, t_owner, t_prio, t_stat, t_dl in tasks_data:
            existing_t = db.query(TaskItem).filter(
                TaskItem.project_id == proj.id,
                TaskItem.title == t_title
            ).first()
            if not existing_t:
                db.add(TaskItem(
                    id=str(uuid.uuid4()),
                    project_id=proj.id,
                    title=t_title,
                    description=t_desc,
                    owner=t_owner,
                    priority=t_prio,
                    status=t_stat,
                    deadline=t_dl,
                    created_at=now,
                    updated_at=now,
                ))
                print("Added Task:", t_title)

        # 9. Seed Comprehensive Handover Dossier & Sections
        handover = db.query(Handover).filter(Handover.project_id == proj.id).first()
        if not handover:
            handover = Handover(
                id=str(uuid.uuid4()),
                project_id=proj.id,
                created_by_user_id=user.id,
                title="TEAM OBSIDIAN: Master Architecture & Knowledge Handover Dossier v2.0",
                departing_employee_name="Dr. Evelyn Reed",
                departing_employee_role="Principal Systems Architect",
                incoming_employee_name="Judge Evaluator (Demo)",
                incoming_employee_role="Lead Software Evaluator",
                status="approved",
                target_date=(now + timedelta(days=14)).strftime("%Y-%m-%d"),
                overall_confidence=0.96,
                reconstruction_stats={
                    "sources_analyzed": 142,
                    "graph_nodes": 86,
                    "dependencies_mapped": 24,
                    "unverified_claims": 0,
                    "readiness_score": 94.5,
                },
            )
            db.add(handover)
            db.flush()
            print("Created Handover Dossier:", handover.title)
        else:
            handover.title = "TEAM OBSIDIAN: Master Architecture & Knowledge Handover Dossier v2.0"
            handover.overall_confidence = 0.96
            handover.status = "approved"
            handover.reconstruction_stats = {
                "sources_analyzed": 142,
                "graph_nodes": 86,
                "dependencies_mapped": 24,
                "unverified_claims": 0,
                "readiness_score": 94.5,
            }
            print("Updated Handover Dossier:", handover.title)

        sections_data = [
            (1, "Executive Summary & System Vision", """TEAM OBSIDIAN was architected to eliminate enterprise tribal knowledge silos by turning raw engineering artifacts (code syntax trees, commits, PR discussions, Slack incident threads, and Confluence wikis) into an interactive, verifiable dependency graph.

The system is fully production-ready, featuring 8 verified connectors, end-to-end AES-256 credential encryption, and a dual-engine LLM hierarchy. This dossier provides the incoming engineering team with complete architectural clarity, disaster recovery runbooks, and risk mitigations."""),
            (2, "Core Microservices Architecture & Data Flow", """The platform follows an asynchronous, event-driven architecture:
1. **API Tier (FastAPI)**: Serves authenticated REST and WebSocket clients with rate-limiting, CORS enforcement, and security headers.
2. **Worker Tier**: Celery / Redis workers executing background AST parsing, embedding computation, and webhook ingestion.
3. **Storage Tier (Supabase PostgreSQL)**: 18 relational tables with foreign-key referential integrity, pgvector indexes, and connection poolers.
4. **Integration Tier (Nango)**: Multi-tenant credential management supporting both personal OAuth and organization-level app installations."""),
            (3, "Critical Single Points of Failure (SPOFs) & Blast Radius", """Three primary SPOFs have been catalogued and mitigated:
- **SPOF-01 (Payment Webhook Handler)**: Critical module originally maintained solely by Dr. Evelyn Reed. Mitigated by comprehensive code walkthrough, automated unit tests, and signature rotation protocols.
- **SPOF-02 (Single-Region Database Pooler)**: Mitigated by failover playbooks and standby replication in Supabase.
- **SPOF-03 (Token Expiration Cascade)**: Mitigated by 4-hour health checks, automated token refresh, and fallback Basic Auth."""),
            (4, "Operational Runbooks, Failover & Key Rotation", """Operational excellence guidelines:
- **Secret Rotation**: Rotate `CREDENTIALS_ENCRYPTION_KEY` and Nango environment keys every 90 days.
- **Database Backup**: Automated daily snapshots with 30-day point-in-time recovery (PITR).
- **Incident Escalation**: P0/P1 alerts route to PagerDuty with Slack notifications in `#all-new-workspace`."""),
            (5, "Platform Permissions & Access Matrix", """All 8 external integrations have been verified:
- GitHub: `teamobsidian44/Data` (Admin PAT)
- Jira Cloud: `teamobsidian44.atlassian.net` (Project KAN & SAM1)
- Confluence: Space OBS (Knowledge Base)
- Linear: Team TEA (Roadmaps & Cycles)
- GitLab: `team-obsidian-group/team-obsidian-project`
- Sentry: Organization `team-obsidian`
- Slack: Workspace `New Workspace` (#all-new-workspace, #social)
- Notion: Database `414735e0-f0cf-801e-8d99-d833248332df`"""),
            (6, "Knowledge Gap Action Plan & 14-Day Ramp-Up", """Detailed 14-day milestones for incoming lead architect:
- **Week 1**: Complete environment setup, review all 5 ADRs, shadow live PR reviews.
- **Week 2**: Execute simulated database failover drill, complete exit interview questions, sign off on Handover Dossier v2.0, and assume primary on-call rotation."""),
        ]

        for sec_num, sec_title, sec_content in sections_data:
            existing_sec = db.query(HandoverSection).filter(
                HandoverSection.handover_id == handover.id,
                HandoverSection.section_number == sec_num
            ).first()
            if not existing_sec:
                db.add(HandoverSection(
                    id=str(uuid.uuid4()),
                    handover_id=handover.id,
                    section_number=sec_num,
                    title=sec_title,
                    content=sec_content,
                    is_verified=True,
                    verification_status="verified",
                    confidence=0.95,
                    updated_at=now,
                ))
                print(f"Added Handover Section {sec_num}: {sec_title}")
            else:
                existing_sec.title = sec_title
                existing_sec.content = sec_content
                existing_sec.is_verified = True
                existing_sec.verification_status = "verified"

        # 10. Seed Handover Approvals
        approvals_data = [
            ("Dr. Evelyn Reed", "Principal Systems Architect (Departing)", "approved", "Full architecture and AST dependency maps verified.", now - timedelta(days=1), 1, True),
            ("Marcus Vance", "Head of Engineering", "approved", "Knowledge transfer milestones and risk mitigations accepted.", now - timedelta(hours=12), 2, True),
            ("Sarah Lin", "Lead Security Architect", "approved", "Zero-trust token encryption and RLS policies audited.", now - timedelta(hours=6), 3, True),
            ("Judge Evaluator (Demo)", "Lead Software Evaluator (Incoming)", "pending_review", "Awaiting final evaluator review and sign-off in the UI.", None, 4, True),
        ]

        for a_name, a_role, a_stat, a_notes, a_signed, a_idx, a_req in approvals_data:
            existing_app = db.query(HandoverApproval).filter(
                HandoverApproval.handover_id == handover.id,
                HandoverApproval.approver_name == a_name
            ).first()
            if not existing_app:
                db.add(HandoverApproval(
                    id=str(uuid.uuid4()),
                    handover_id=handover.id,
                    approver_name=a_name,
                    role=a_role,
                    status=a_stat,
                    notes=a_notes,
                    signed_at=a_signed,
                    order_index=a_idx,
                    is_required=a_req,
                    created_at=now,
                ))
                print("Added Handover Approval:", a_name)

        # 11. Seed Exit Interview Questions
        exit_q_data = [
            (1, "Why did the team migrate background queues from in-memory threading to BullMQ & Redis?", "In-memory threading caused unacknowledged job loss during container restarts on Render. BullMQ provides durable message queues, concurrency controls, and dead-letter queues for heavy AST extractions.", "verified", "P1"),
            (2, "How are external platform credentials secured across multiple user devices?", "Credentials are encrypted at rest using AES-256-GCM and stored in Supabase PostgreSQL, linked by user ID and project ID. They are never stored in browser LocalStorage or cookies.", "verified", "P1"),
            (3, "What is the failover strategy if the primary database pooler encounters network isolation?", "Execute the Disaster Recovery playbook to promote the standby read replica in Supabase. The backend engine automatically retries pool connections with exponential backoff.", "verified", "P1"),
            (4, "How does the AI assistant guarantee zero hallucinations when answering architecture questions?", "The assistant uses multi-entity graph RAG with strict citation thresholds. Every generated claim must cite an indexed document chunk, commit hash, or Jira ticket, or the engine abstains.", "verified", "P2"),
            (5, "What is the highest-priority architectural task remaining for the incoming lead architect?", "Complete the end-to-end dual-key HMAC webhook verification for incoming Slack and GitLab events to ensure zero-downtime secret rotations.", "verified", "P1"),
        ]

        for q_num, q_text, a_text, q_stat, q_prio in exit_q_data:
            existing_q = db.query(ExitInterviewQuestion).filter(
                ExitInterviewQuestion.handover_id == handover.id,
                ExitInterviewQuestion.question_text == q_text
            ).first()
            if not existing_q:
                db.add(ExitInterviewQuestion(
                    id=str(uuid.uuid4()),
                    handover_id=handover.id,
                    project_id=proj.id,
                    section_number=q_num,
                    question_text=q_text,
                    answer_text=a_text,
                    status=q_stat,
                    priority=q_prio,
                    created_by_user_id=user.id,
                    answered_by_user_id=user.id,
                    answered_at=now,
                    created_at=now,
                    updated_at=now,
                ))
                print(f"Added Exit Question {q_num}")

        # 12. Seed Readiness Simulation
        existing_sim = db.query(ReadinessSimulation).filter(
            ReadinessSimulation.handover_id == handover.id
        ).first()
        if not existing_sim:
            db.add(ReadinessSimulation(
                id=str(uuid.uuid4()),
                handover_id=handover.id,
                project_id=proj.id,
                user_id=user.id,
                candidate_name="Judge Evaluator (Demo)",
                overall_score=94.5,
                passed=True,
                scenarios_json=[
                    {
                        "scenario_id": "SIM-01",
                        "title": "Database Connection Pool Exhaustion Drill",
                        "score": 96.0,
                        "status": "passed",
                        "feedback": "Correctly identified pooler exhaustion in Supabase and executed backoff connection throttle."
                    },
                    {
                        "scenario_id": "SIM-02",
                        "title": "OAuth Access Token Revocation Recovery",
                        "score": 94.0,
                        "status": "passed",
                        "feedback": "Successfully utilized Nango token refresh protocol and verified status recovery without downtime."
                    },
                    {
                        "scenario_id": "SIM-03",
                        "title": "Payment Webhook Idempotency Verification",
                        "score": 93.5,
                        "status": "passed",
                        "feedback": "Validated signature replay protection and inspected event deduplication logs."
                    }
                ],
                responses_json={"candidate": "Judge Evaluator", "mode": "evaluation_drill", "duration_minutes": 24},
                summary_feedback="EXCELLENT READINESS (94.5%): Candidate demonstrates complete operational and architectural competence. Qualified to assume primary on-call and deployment authority.",
                created_at=now,
            ))
            print("Added Readiness Simulation Record (Score: 94.5%)")

        db.commit()
        print("\nSUCCESS: All rich project details, documents, knowledge entities, relationships, ADRs, risks, gaps, tasks, handover sections, approvals, exit questions, and simulations seeded successfully to Supabase PostgreSQL!")
    finally:
        db.close()

if __name__ == '__main__':
    run()
