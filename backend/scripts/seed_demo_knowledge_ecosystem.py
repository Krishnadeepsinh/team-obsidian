"""
Enterprise Knowledge Ecosystem Seed Script for TEAM OBSIDIAN
Populates authentic, interconnected data across all 8 platforms:
1. GitHub: Code AST, architecture docs, commits, PRs, issues (also pushed to GitHub API for teamobsidian44/Data)
2. Slack: Architecture decision channels, incident war rooms, escalation threads
3. Notion: Technical specifications, system runbooks, onboarding playbooks
4. Jira Cloud: Epics, user stories, engineering tasks, sprint blockers
5. Confluence: Architecture Decision Records (ADRs), postmortems, system topology wikis
6. Linear: Cycles, project roadmap milestones, issue tracking
7. GitLab: CI/CD configuration files, merge requests, AST code records
8. Sentry: Live error telemetry, stack traces, culprits, error events
"""

import os
import sys
import uuid
import hashlib
import json
from datetime import datetime, timezone, timedelta
import httpx
import base64

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal
from app.core.config import settings
from app.core.security import encrypt_credentials
from app.models.workspace import Project, User, Organization, Workspace, ProjectMember
from app.models.integration import Integration, SourceRecord
from app.models.knowledge import (
    KnowledgeEntity,
    KnowledgeRelationship,
    Decision,
    TaskItem,
    Dependency,
    RiskItem,
)
from app.models.handover import (
    Handover,
    HandoverSection,
    HandoverClaim,
)


PROJECT_ID = "f51869e7-b07c-47e4-9984-a54862c9d3ad"
DEMO_EMAIL = "team.obsidian44@gmail.com"
GITHUB_REPO = "teamobsidian44/Data"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 1. Push Real Code & Architecture Files to GitHub API (teamobsidian44/Data)
# ---------------------------------------------------------------------------
def push_files_to_github():
    token = settings.GITHUB_TOKEN
    if not token:
        print("[GitHub] No GITHUB_TOKEN configured in settings, skipping API push.")
        return

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    files = {
        "src/core/knowledge_engine.py": '''"""
Team Obsidian — Distributed AST Knowledge Extraction Engine
Parses multi-language codebases using Tree-sitter, extracts semantic entities,
and constructs high-density dependency graphs for architectural handovers.
"""

import ast
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class AstGraphParser:
    """Extracts classes, functions, and cross-module import dependencies."""

    def __init__(self, language: str = "python"):
        self.language = language
        self.entities: List[Dict[str, Any]] = []
        self.dependencies: List[Dict[str, str]] = []

    def parse_python_module(self, source_code: str, file_path: str) -> Dict[str, Any]:
        """Parse Python source into AST and extract structural symbols."""
        try:
            tree = ast.parse(source_code, filename=file_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    self.entities.append({
                        "name": node.name,
                        "entity_type": "class",
                        "line_start": node.lineno,
                        "docstring": ast.get_docstring(node) or "",
                        "file_path": file_path,
                    })
                elif isinstance(node, ast.FunctionDef):
                    self.entities.append({
                        "name": node.name,
                        "entity_type": "function",
                        "line_start": node.lineno,
                        "docstring": ast.get_docstring(node) or "",
                        "file_path": file_path,
                    })
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    mod_name = getattr(node, "module", None) or ", ".join(n.name for n in node.names)
                    self.dependencies.append({
                        "source": file_path,
                        "target": mod_name,
                        "dep_type": "import",
                    })
            return {"entities": self.entities, "dependencies": self.dependencies, "status": "success"}
        except SyntaxError as e:
            logger.error("AST syntax parsing failure in %s: %s", file_path, e)
            return {"entities": [], "dependencies": [], "status": "error", "error": str(e)}


class KnowledgeEntityExtractor:
    """Semantic classifier for architectural components, APIs, and data layers."""

    @staticmethod
    def classify_architecture_tier(file_path: str) -> str:
        if "api" in file_path or "routes" in file_path:
            return "api_gateway"
        if "core" in file_path or "engine" in file_path:
            return "core_business_logic"
        if "services" in file_path or "connectors" in file_path:
            return "external_integration_tier"
        if "models" in file_path or "db" in file_path:
            return "persistence_layer"
        return "general_utility"
''',
        "src/auth/nango_bridge.ts": '''/**
 * Team Obsidian — Universal Nango Integration & Token Broker
 * Manages OAuth handshakes, refresh loops, and scope verification across
 * GitHub, Slack, Notion, Jira, Confluence, Linear, GitLab, and Sentry.
 */

export interface NangoConnectionConfig {
  connectionId: string;
  providerConfigKey: string;
  scopes: string[];
  expiresAt?: string;
}

export class UniversalConnectorBroker {
  private baseUri: string;
  private apiKey: string;

  constructor(apiKey: string, baseUri: string = "https://api.nango.dev") {
    this.apiKey = apiKey;
    this.baseUri = baseUri;
  }

  async verifyConnection(config: NangoConnectionConfig): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseUri}/connection/${config.connectionId}?provider_config_key=${config.providerConfigKey}`, {
        headers: { Authorization: `Bearer ${this.apiKey}` },
      });
      return response.ok;
    } catch (err) {
      console.error(`Failed to verify Nango connection:`, err);
      return false;
    }
  }

  async rotateCredentials(connectionId: string, provider: string): Promise<string> {
    // Automated OAuth token refresh loop
    return `rotated_token_obsidian_${provider}_${Date.now()}`;
  }
}
''',
        "src/services/telemetry_stream.py": '''"""
Team Obsidian — Real-time Sentry Telemetry & Distributed Error Correlator
Maps live production stack traces to AST code symbols and architecture nodes.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class SentryTelemetrySubscriber:
    """Subscribes to Sentry error webhooks and correlates issues to Git commits."""

    def __init__(self, project_slug: str):
        self.project_slug = project_slug

    def process_error_event(self, event_payload: Dict[str, Any]) -> Dict[str, Any]:
        culprit = event_payload.get("culprit", "unknown")
        exception_type = event_payload.get("exception_type", "RuntimeError")
        stack_trace = event_payload.get("stack_trace", "")
        level = event_payload.get("level", "error")

        logger.info("Processing Sentry issue: %s (%s)", exception_type, culprit)
        return {
            "issue_id": event_payload.get("id"),
            "culprit": culprit,
            "exception_type": exception_type,
            "severity": level,
            "mapped_ast_node": culprit.split(".")[-1] if "." in culprit else culprit,
        }
''',
        "docs/ARCHITECTURE.md": '''# Team Obsidian — System Architecture Blueprint

## 1. High-Level Overview
Team Obsidian ingests organizational knowledge across 8 distinct SaaS platforms into a unified architectural knowledge graph:
- **Code & Version Control**: GitHub & GitLab
- **Communication & Incident Rooms**: Slack
- **Specifications & Runbooks**: Notion & Confluence
- **Issue Tracking & Roadmaps**: Jira Cloud & Linear
- **Runtime Telemetry & Error Streams**: Sentry

## 2. Ingestion & Graph Protocol
```
[SaaS Connectors] -> [Nango Universal Gateway] -> [AST Tree-sitter Engine] -> [Unified Graph DB]
                                                          |
                                                 [Sentry Telemetry]
```

## 3. Resilience & Multi-Tenant Boundaries
- All provider credentials are encrypted at rest using AES-256-GCM.
- Per-tenant database row-level security isolates customer graphs.
- Webhook signature verification guarantees cryptographic integrity.
''',
        "docs/RUNBOOK_DISASTER_RECOVERY.md": '''# P0 Disaster Recovery & Multi-Cloud Failover Runbook

## Service: Team Obsidian Knowledge Gateway
- **Target RTO**: < 15 minutes
- **Target RPO**: < 1 hour

### 1. Alerting Triggers
- Sentry alert: `RedisConnectionPoolTimeout` > 10 events / min
- API Healthcheck `GET /health` latency > 2000ms

### 2. Immediate Mitigation Actions
1. Restart worker pool: `systemctl restart obsidian-worker`
2. Clear dead Redis connection handles: `redis-cli client kill type normal`
3. Verify database replication health: `SELECT * FROM pg_stat_replication;`
''',
    }

    for path, code in files.items():
        try:
            # Check if file exists to get sha
            get_r = httpx.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}", headers=headers)
            sha = get_r.json().get("sha") if get_r.status_code == 200 else None

            payload = {
                "message": f"feat(core): add {path} architecture definition",
                "content": base64.b64encode(code.encode("utf-8")).decode("ascii"),
                "branch": "main",
            }
            if sha:
                payload["sha"] = sha

            put_r = httpx.put(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}", headers=headers, json=payload)
            if put_r.status_code in [200, 201]:
                print(f"[GitHub API] Successfully pushed {path}")
            else:
                print(f"[GitHub API] Push {path} response: {put_r.status_code}")
        except Exception as e:
            print(f"[GitHub API] Push error for {path}: {e}")

    # Create issues
    issues = [
        {"title": "Architecture: Implement Tree-sitter AST dependency extraction", "body": "Need to extract full class, method, and import graphs for TypeScript and Python."},
        {"title": "Telemetry: Map Sentry production stack traces directly to AST nodes", "body": "Enable instant jump from Sentry error culprits to AST nodes in Knowledge Explorer."},
        {"title": "Security: Standardize Nango OAuth token rotation across all 8 platforms", "body": "Enforce automated OAuth token refresh and AES-256 credential encryption."},
    ]
    for iss in issues:
        try:
            r = httpx.post(f"https://api.github.com/repos/{GITHUB_REPO}/issues", headers=headers, json=iss)
            if r.status_code in [200, 201]:
                print(f"[GitHub API] Created issue: {iss['title']}")
        except Exception as e:
            print(f"[GitHub API] Issue creation error: {e}")


# ---------------------------------------------------------------------------
# 2. Seed Database with Comprehensive Multi-Source Records & Graph Entities
# ---------------------------------------------------------------------------
def seed_database_ecosystem():
    db = SessionLocal()
    try:
        proj = db.query(Project).filter(Project.id == PROJECT_ID).first()
        if not proj:
            print(f"[DB] Project {PROJECT_ID} not found. Aborting.")
            return

        user = db.query(User).filter(User.email == DEMO_EMAIL).first()
        if not user:
            user = db.query(User).first()

        print(f"[DB] Seeding ecosystem for Project: {proj.name} ({proj.id})")

        # Ensure all 8 Integrations exist and are connected & verified
        providers = [
            ("github", "GitHub (teamobsidian44/Data)", "teamobsidian44", {"repository": "teamobsidian44/Data", "repos": ["teamobsidian44/Data"]}),
            ("slack", "Slack (New Workspace #all-new-workspace)", "New Workspace", {"channel": "all-new-workspace", "channels": ["all-new-workspace", "architecture", "incident-response"]}),
            ("notion", "Notion (Welcome to Notion)", "Team Obsidian Workspace", {"workspace": "Team Obsidian"}),
            ("jira", "Jira Cloud (KAN)", "teamobsidian44.atlassian.net", {"site_url": "https://teamobsidian44.atlassian.net", "project_key": "KAN"}),
            ("confluence", "Confluence (OBS)", "teamobsidian44.atlassian.net", {"site_url": "https://teamobsidian44.atlassian.net", "space_key": "OBS"}),
            ("linear", "Linear (TEA)", "teamobsidian", {"team_key": "TEA"}),
            ("gitlab", "GitLab (team-obsidian-project)", "team.obsidian44", {"project": "team-obsidian-project"}),
            ("sentry", "Sentry (team-obsidian)", "team-obsidian", {"organization": "team-obsidian", "project": "team-obsidian"}),
        ]

        integ_map = {}
        for prov, name, acct, cfg in providers:
            integ = db.query(Integration).filter(Integration.project_id == proj.id, Integration.provider == prov).first()
            if not integ:
                integ = Integration(
                    project_id=proj.id,
                    workspace_id=proj.workspace_id,
                    user_id=user.id,
                    authorized_by_user_id=user.id,
                    authorized_by_email=user.email,
                    connection_type="organization",
                    provider=prov,
                    name=name,
                    auth_type="api_token",
                    auth_status="verified",
                    connected_account=acct,
                    credentials=encrypt_credentials({"is_demo": True, "token": f"live_demo_{prov}_token", "account": acct}),
                    config=cfg,
                    status="connected",
                    items_synced=12,
                )
                db.add(integ)
                db.flush()
            else:
                integ.status = "connected"
                integ.auth_status = "verified"
                integ.connected_account = acct
                integ.name = name
                integ.config = cfg
                db.flush()
            integ_map[prov] = integ

        print(f"[DB] All 8 integrations configured and verified.")

        # Source Records across all 8 platforms
        records_data = [
            # 1. GitHub
            {
                "prov": "github",
                "ext_id": "gh-file-knowledge-engine",
                "title": "src/core/knowledge_engine.py: AstGraphParser & KnowledgeEntityExtractor",
                "author": "teamobsidian44",
                "url": "https://github.com/teamobsidian44/Data/blob/main/src/core/knowledge_engine.py",
                "content": """Module: src/core/knowledge_engine.py
AST Parser & Semantic Knowledge Extractor.
Defines AstGraphParser for Tree-sitter code graph construction and KnowledgeEntityExtractor for classifying architectural layers.
Key Classes:
- AstGraphParser: Walks AST, indexes class definitions, function signatures, and cross-file imports.
- KnowledgeEntityExtractor: Categorizes files into API Gateway, Core Business Logic, and Persistence Layer.""",
                "meta": {"file_path": "src/core/knowledge_engine.py", "language": "python", "symbols": ["AstGraphParser", "KnowledgeEntityExtractor"]},
            },
            {
                "prov": "github",
                "ext_id": "gh-file-nango-bridge",
                "title": "src/auth/nango_bridge.ts: UniversalConnectorBroker & Token Rotation",
                "author": "teamobsidian44",
                "url": "https://github.com/teamobsidian44/Data/blob/main/src/auth/nango_bridge.ts",
                "content": """Module: src/auth/nango_bridge.ts
Universal Nango Connector Broker.
Implements UniversalConnectorBroker for OAuth validation, token rotation loops, and provider permission handshakes.
Handles token lifecycles for GitHub, Slack, Notion, Jira, Confluence, Linear, GitLab, and Sentry.""",
                "meta": {"file_path": "src/auth/nango_bridge.ts", "language": "typescript", "symbols": ["UniversalConnectorBroker", "NangoConnectionConfig"]},
            },
            {
                "prov": "github",
                "ext_id": "gh-pr-1",
                "title": "PR #1: feat(ast): Add cross-platform Python and TypeScript AST extraction",
                "author": "teamobsidian44",
                "url": "https://github.com/teamobsidian44/Data/pull/1",
                "content": """Pull Request #1: feat(ast): Add cross-platform Python and TypeScript AST extraction
Merges the tree-sitter indexing pipeline into main. Resolves ticket KAN-102 and TEA-42.
Reviewed by Staff Engineer. All unit tests passing (100% test coverage on AST visitors).""",
                "meta": {"pr_number": 1, "state": "merged", "merged_at": "2026-11-16T14:00:00Z"},
            },

            # 2. Slack
            {
                "prov": "slack",
                "ext_id": "slack-arch-adr042",
                "title": "#architecture: Architectural Decision Thread — Hybrid Vector vs Graph RAG",
                "author": "Alex Vance (Staff Arch)",
                "url": "https://newworkspace-snx1773.slack.com/archives/C0C4T5JCHM3/p1731600000",
                "content": """[#architecture Channel Discussion]
Alex Vance: Team, for the handover intelligence engine, vector embeddings alone suffer from hallucination on multi-hop dependencies. We are adopting a Hybrid Graph-RAG architecture (ADR-042).
Sarah Chen: Strongly agree. With AST dependency trees from GitHub and GitLab, we can traverse caller-callee hierarchies deterministically, using vector similarity only for fuzzy topic search.
Marcus Reed: Benchmarked the graph traversal on 50k nodes. Latency is under 18ms with Redis caching.""",
                "meta": {"channel": "#architecture", "thread_ts": "1731600000.000100", "replies": 8},
            },
            {
                "prov": "slack",
                "ext_id": "slack-incident-redis",
                "title": "#incident-response: War Room Retrospective — P0 Redis Connection Pool Saturation",
                "author": "Incident Commander",
                "url": "https://newworkspace-snx1773.slack.com/archives/C0C4T5JCHM3/p1731700000",
                "content": """[#incident-response Incident War Room]
Incident Commander: 2026-11-04 P0 Outage resolved. Root cause was high burst telemetry from Sentry webhooks depleting Redis client connections in telemetry_stream.py.
Resolution: Deployed circuit breaker with 50-connection max pool cap and async batch queueing.
Action Item: KAN-104 created in Jira to backport connection health checks.""",
                "meta": {"channel": "#incident-response", "incident_id": "INC-2026-11-04", "severity": "P0"},
            },

            # 3. Notion
            {
                "prov": "notion",
                "ext_id": "notion-spec-platform",
                "title": "PRD: Team Obsidian Enterprise Knowledge Transfer Platform v2.0",
                "author": "Product Lead",
                "url": "https://notion.so/team-obsidian/PRD-Knowledge-Platform-v2",
                "content": """Product Requirement Document: Team Obsidian Enterprise Knowledge Transfer Platform.
1. Problem: Departing engineers take critical architectural, operational, and incident tribal knowledge with them, causing costly downtime and onboarding friction.
2. Solution: Autonomous multi-platform ingestion (GitHub, Slack, Jira, Confluence, Linear, Notion, GitLab, Sentry) mapped into an interactive AST Knowledge Graph with automated Handover generation.
3. Acceptance Criteria: Sub-second graph rendering, 100% audit logging, and zero-token loss across handovers.""",
                "meta": {"doc_type": "PRD", "status": "Approved", "version": "2.0"},
            },
            {
                "prov": "notion",
                "ext_id": "notion-onboarding-playbook",
                "title": "Staff Engineer First 30 Days: System Architecture & Handover Guide",
                "author": "Engineering Director",
                "url": "https://notion.so/team-obsidian/Staff-Engineer-First-30-Days",
                "content": """Staff Engineer Onboarding Playbook.
Welcome to Team Obsidian. This guide walks you through:
- Reading the architecture blueprint in Confluence (ADR-001 through ADR-003).
- Setting up the local Docker development environment and running pytest suites.
- Accessing production telemetry in Sentry and navigating the Knowledge Explorer.
- Understanding the Nango Universal OAuth integration topology.""",
                "meta": {"doc_type": "Onboarding", "audience": "Engineering Leads"},
            },

            # 4. Jira Cloud
            {
                "prov": "jira",
                "ext_id": "KAN-101",
                "title": "[KAN-101] Epic: Unified Knowledge Graph Extraction & Storage Engine",
                "author": "Engineering Lead",
                "url": "https://teamobsidian44.atlassian.net/browse/KAN-101",
                "content": """Issue: KAN-101 (Epic)
Summary: Unified Knowledge Graph Extraction & Storage Engine
Description: Build the core ingestion and graph synthesis pipeline uniting code repositories, incident channels, and documentation wikis into a unified PostgreSQL and Neo4j graph model.
Status: Completed
Story Points: 21""",
                "meta": {"issue_key": "KAN-101", "issue_type": "Epic", "status": "Done"},
            },
            {
                "prov": "jira",
                "ext_id": "KAN-104",
                "title": "[KAN-104] Bug: Fix Redis Connection Pool Starvation in Telemetry Subscriber",
                "author": "SRE On-Call",
                "url": "https://teamobsidian44.atlassian.net/browse/KAN-104",
                "content": """Issue: KAN-104 (Bug)
Summary: Fix Redis Connection Pool Starvation in Telemetry Subscriber
Description: Under heavy burst telemetry from Sentry, connection handles in src/services/telemetry_stream.py were not being returned to the pool, triggering HTTP 503 gateway timeouts.
Fix: Implement context manager connection pooling with automatic backoff.
Status: Resolved""",
                "meta": {"issue_key": "KAN-104", "issue_type": "Bug", "priority": "High", "status": "Resolved"},
            },

            # 5. Confluence
            {
                "prov": "confluence",
                "ext_id": "conf-adr-002",
                "title": "ADR-002: Hybrid Knowledge Graph & Vector Retrieval Architecture",
                "author": "Architecture Council",
                "url": "https://teamobsidian44.atlassian.net/wiki/spaces/OBS/pages/1002/ADR-002",
                "content": """Architecture Decision Record 002:
Title: Hybrid Knowledge Graph & Vector Retrieval Architecture
Context: Single-paradigm retrieval (vector-only) fails to maintain strict parent-child relationships across code modules, Jira epics, and Slack escalation threads.
Decision: Combine hierarchical Graph traversal with dense vector similarity search.
Consequences: Guaranteed precision for code dependency exploration; sub-20ms query latency; zero hallucinated relationships.""",
                "meta": {"space": "OBS", "adr_number": 2, "status": "Accepted"},
            },
            {
                "prov": "confluence",
                "ext_id": "conf-postmortem-redis",
                "title": "Postmortem: 2026-11-04 Telemetry Ingestion Pool Starvation Outage",
                "author": "DevOps Lead",
                "url": "https://teamobsidian44.atlassian.net/wiki/spaces/OBS/pages/1004/Postmortem-Redis",
                "content": """Postmortem Document: 2026-11-04 Telemetry Ingestion Pool Starvation
Duration: 14 minutes.
Impact: Delayed ingestion of real-time Sentry telemetry events.
Root Cause: Thread pool starvation in telemetry_stream.py.
Preventative Actions:
1. Hardened connection limits to 50 concurrent handles.
2. Added circuit breakers in API gateway.
3. Added automated PagerDuty alert for connection pool exhaustion.""",
                "meta": {"space": "OBS", "type": "Postmortem", "status": "Published"},
            },

            # 6. Linear
            {
                "prov": "linear",
                "ext_id": "TEA-42",
                "title": "TEA-42: Implement Tree-sitter AST dependency graph parser for Python & TypeScript",
                "author": "Core Eng",
                "url": "https://linear.app/teamobsidian/issue/TEA-42",
                "content": """Linear Issue: TEA-42
Cycle: Cycle 14 (Knowledge Core Launch)
State: Done
Description: Implement multi-language AST extraction in backend/app/services/code_ast_indexer.py. Index functions, classes, and dependencies directly into KnowledgeEntity tables.""",
                "meta": {"cycle": "Cycle 14", "priority": "High", "state": "Done"},
            },

            # 7. GitLab
            {
                "prov": "gitlab",
                "ext_id": "gitlab-ci-yml",
                "title": ".gitlab-ci.yml: Multi-Stage CI/CD Pipeline & Automated Security Scan",
                "author": "team.obsidian44",
                "url": "https://gitlab.com/team.obsidian44/team-obsidian-project/-/blob/main/.gitlab-ci.yml",
                "content": """GitLab CI/CD Pipeline Definition:
stages:
  - lint
  - test
  - security_scan
  - build

test_backend:
  stage: test
  script:
    - pytest backend/tests/ --cov=app

security_audit:
  stage: security_scan
  script:
    - bandit -r app/
    - semgrep --config=p/owasp-top-ten""",
                "meta": {"pipeline": "GitLab CI/CD", "branch": "main"},
            },

            # 8. Sentry
            {
                "prov": "sentry",
                "ext_id": "sentry-issue-redis-timeout",
                "title": "RedisConnectionPoolTimeout: Connection pool exhausted in telemetry_stream.py:142",
                "author": "Sentry Telemetry Bot",
                "url": "https://sentry.io/organizations/team-obsidian/issues/4829104/",
                "content": """Sentry Issue: PROD-API-428
Exception: RedisConnectionPoolTimeout: Connection pool exhausted (max 50 active handles)
Culprit: src/services/telemetry_stream.py in process_error_event at line 142
Event Count: 42 events | Users Affected: 12
Stack Trace:
  File "src/services/telemetry_stream.py", line 142, in process_error_event
    client = redis_pool.get_connection()
  File "redis/connection.py", line 1380, in get_connection
    raise ConnectionError("Connection pool exhausted")""",
                "meta": {"level": "error", "culprit": "src/services/telemetry_stream.py:142", "first_seen": "2026-11-04T10:12:00Z"},
            },
        ]

        # Insert / Update SourceRecords
        for rd in records_data:
            prov = rd["prov"]
            integ = integ_map[prov]
            existing_rec = db.query(SourceRecord).filter(
                SourceRecord.project_id == proj.id,
                SourceRecord.source_type == prov,
                SourceRecord.external_id == rd["ext_id"],
            ).first()

            hash_val = sha256(rd["content"])
            if existing_rec:
                existing_rec.title = rd["title"]
                existing_rec.content = rd["content"]
                existing_rec.metadata_json = rd["meta"]
                existing_rec.sha256_hash = hash_val
                existing_rec.url = rd["url"]
                existing_rec.author = rd["author"]
            else:
                new_rec = SourceRecord(
                    id=str(uuid.uuid4()),
                    project_id=proj.id,
                    integration_id=integ.id,
                    source_type=prov,
                    external_id=rd["ext_id"],
                    title=rd["title"],
                    author=rd["author"],
                    url=rd["url"],
                    content=rd["content"],
                    metadata_json=rd["meta"],
                    raw_payload={"raw": rd["title"]},
                    sha256_hash=hash_val,
                    source_timestamp=datetime.now(timezone.utc) - timedelta(days=2),
                )
                db.add(new_rec)
        db.flush()
        print(f"[DB] Inserted/updated {len(records_data)} SourceRecords.")

        # -------------------------------------------------------------------
        # 3. Knowledge Entities, Dependencies, Decisions, Risks, Tasks
        # -------------------------------------------------------------------
        entities = [
            ("AstGraphParser", "class", "Core Tree-sitter code parser extracting classes, functions, and imports.", "high", "src/core/knowledge_engine.py"),
            ("KnowledgeEntityExtractor", "class", "Categorizes AST nodes into architectural tiers and modules.", "medium", "src/core/knowledge_engine.py"),
            ("UniversalConnectorBroker", "class", "Universal OAuth broker managing authentication across all 8 platforms.", "critical", "src/auth/nango_bridge.ts"),
            ("SentryTelemetrySubscriber", "service", "Subscribes to Sentry error streams and correlates stack traces with AST nodes.", "high", "src/services/telemetry_stream.py"),
            ("RedisConnectionPool", "infrastructure", "Redis connection management pool supporting distributed telemetry stream.", "critical", "redis://cluster"),
            ("HybridGraphRetriever", "component", "Combines knowledge graph relational traversal with dense vector similarity.", "critical", "app/services/retrieval_service.py"),
            ("DisasterRecoveryRunbook", "documentation", "Operational runbook for P0 incident failovers and cluster recovery.", "high", "docs/RUNBOOK_DISASTER_RECOVERY.md"),
            ("ADR-042: Hybrid Retrieval", "decision", "Formal decision record standardizing hybrid graph-vector architecture.", "medium", "docs/ADR-042.md"),
        ]

        entity_objs = {}
        for name, etype, desc, imp, loc in entities:
            e = db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == proj.id, KnowledgeEntity.name == name).first()
            if not e:
                e = KnowledgeEntity(
                    id=str(uuid.uuid4()),
                    project_id=proj.id,
                    created_by_user_id=user.id,
                    name=name,
                    entity_type=etype,
                    description=desc,
                    properties={"source_location": loc, "importance": imp},
                    confidence=0.98,
                    verification_status="verified",
                )
                db.add(e)
                db.flush()
            entity_objs[name] = e

        # Dependencies
        dep_pairs = [
            ("AstGraphParser", "HybridGraphRetriever", "provides_nodes_to", "critical"),
            ("UniversalConnectorBroker", "SentryTelemetrySubscriber", "authenticates", "high"),
            ("SentryTelemetrySubscriber", "RedisConnectionPool", "connects_via", "critical"),
            ("HybridGraphRetriever", "ADR-042: Hybrid Retrieval", "implements", "medium"),
            ("RedisConnectionPool", "DisasterRecoveryRunbook", "monitored_by", "high"),
        ]
        for s_name, t_name, rel, crit in dep_pairs:
            existing_dep = db.query(Dependency).filter(
                Dependency.project_id == proj.id,
                Dependency.source_component == s_name,
                Dependency.target_component == t_name,
            ).first()
            if not existing_dep:
                db.add(Dependency(
                    id=str(uuid.uuid4()),
                    project_id=proj.id,
                    source_component=s_name,
                    target_component=t_name,
                    dependency_type=rel,
                    criticality=crit,
                    verification_status="verified",
                ))

        # Decisions (ADRs)
        adrs = [
            ("ADR-001: Microservices Event Fabric", "Adopted Redis Streams for decoupled asynchronous multi-source ingestion.", "approved", "high"),
            ("ADR-002: Hybrid Graph & Vector Retrieval", "Standardized combining AST graph traversal with vector similarity for 0% hallucination.", "approved", "critical"),
            ("ADR-003: Universal Nango Integration Gateway", "Enforce centralized OAuth credential rotation and token isolation via Nango.", "approved", "high"),
        ]
        for title, context, status, imp in adrs:
            existing_d = db.query(Decision).filter(Decision.project_id == proj.id, Decision.title == title).first()
            if not existing_d:
                db.add(Decision(
                    id=str(uuid.uuid4()),
                    project_id=proj.id,
                    created_by_user_id=user.id,
                    title=title,
                    summary=context,
                    reasoning=f"Approved architectural standard with importance {imp}.",
                    decision_maker="Architecture Council",
                    status=status,
                    verification_status="verified",
                    component="Architecture Core",
                    decision_type="architectural",
                    date="2026-11-11",
                ))

        # Risks
        risks = [
            ("Redis Connection Pool Starvation", "High burst telemetry from Sentry webhooks can exhaust pool handles if unthrottled.", "high", "medium", "mitigated"),
            ("OAuth Token Expiration on Inactive Providers", "Third-party tokens can expire if background refresh daemon is delayed.", "medium", "low", "accepted"),
        ]
        for title, desc, sev, prob, status in risks:
            existing_r = db.query(RiskItem).filter(RiskItem.project_id == proj.id, RiskItem.title == title).first()
            if not existing_r:
                db.add(RiskItem(
                    id=str(uuid.uuid4()),
                    project_id=proj.id,
                    created_by_user_id=user.id,
                    title=title,
                    description=desc,
                    category="technical",
                    severity=sev,
                    likelihood=prob,
                    impact=sev,
                    owner="DevOps & Reliability Team",
                    mitigation_strategy="Circuit breaker pattern and automated queue retry.",
                    status=status,
                    verification_status="verified",
                ))

        # Tasks
        tasks = [
            ("KAN-102: Implement Python & TypeScript AST Indexer", "Build AST extraction visitors with Tree-sitter.", "completed", "high"),
            ("KAN-104: Add Circuit Breaker to Telemetry Subscriber", "Cap max active Redis connections at 50 with queue backoff.", "completed", "critical"),
            ("TEA-45: Automate 24-hour OAuth Token Health Checks", "Run background ping across all connected Nango connections.", "in_progress", "medium"),
        ]
        for title, desc, status, prio in tasks:
            existing_t = db.query(TaskItem).filter(TaskItem.project_id == proj.id, TaskItem.title == title).first()
            if not existing_t:
                db.add(TaskItem(
                    id=str(uuid.uuid4()),
                    project_id=proj.id,
                    created_by_user_id=user.id,
                    title=title,
                    description=desc,
                    owner="Staff Engineer",
                    component="Core Engine",
                    priority=prio,
                    status=status,
                    verification_status="verified",
                ))

        # Handover Document
        handover = db.query(Handover).filter(Handover.project_id == proj.id).first()
        if not handover:
            handover = Handover(
                id=str(uuid.uuid4()),
                project_id=proj.id,
                created_by_user_id=user.id,
                title="Master Architectural Handover & Operations Dossier",
                summary="Comprehensive handover documentation covering system topology, all 8 integrations, operational runbooks, and critical failure mitigation strategies.",
                status="approved",
                overall_readiness_score=0.96,
            )
            db.add(handover)
            db.flush()

            # Add Handover Sections
            sections = [
                ("1. Executive Summary & Architecture Topology", "Team Obsidian unifies 8 enterprise integrations (GitHub, Slack, Notion, Jira, Confluence, Linear, GitLab, Sentry) into a single semantic knowledge graph."),
                ("2. AST & Code Dependency Graph", "AstGraphParser and KnowledgeEntityExtractor process repository code to provide multi-hop caller-callee exploration with sub-20ms lookup."),
                ("3. Operational Runbooks & Telemetry Mitigations", "Disaster recovery runbook provides immediate remediation steps for P0 service degradation, Redis pool starvation, and OAuth token rotation."),
                ("4. Credential & Access Matrix", "All provider tokens are encrypted at rest using AES-256-GCM with automated Nango health verification."),
            ]
            for idx, (s_title, s_content) in enumerate(sections, start=1):
                db.add(HandoverSection(
                    id=str(uuid.uuid4()),
                    handover_id=handover.id,
                    section_number=idx,
                    title=s_title,
                    content=s_content,
                    is_verified=True,
                    verification_status="verified",
                    confidence=0.98,
                ))

        db.commit()
        print(f"[DB] Successfully seeded full enterprise knowledge ecosystem for Project {PROJECT_ID}!")

    except Exception as e:
        db.rollback()
        print(f"[DB] Error seeding ecosystem: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    print("=== TEAM OBSIDIAN: Seeding Enterprise Ecosystem ===")
    push_files_to_github()
    seed_database_ecosystem()
    print("=== Complete! ===")
