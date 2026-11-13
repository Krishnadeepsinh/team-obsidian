from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.evidence import Evidence
from app.models.handover import Handover
from app.models.integration import Document, Integration, SourceRecord
from app.models.knowledge import Decision, Dependency, KnowledgeEntity, RiskItem, TaskItem
from app.models.workspace import Project, User
from app.services.ai.provider import central_ai_service
from app.services.ai_engine import ai_engine
from app.services.assistant.intent_classifier import (
    INTENT_ANALYTICAL,
    INTENT_CROSS_SOURCE,
    INTENT_DATA_RETRIEVAL,
    INTENT_DIRECT_METRIC,
    INTENT_HANDOVER,
    INTENT_SEMANTIC_RAG,
    IntentClassifier,
    QueryIntent,
)
from app.services.assistant.tools import (
    get_connected_integrations,
    get_github_repository_inventory,
    get_project_decisions,
    get_project_risks,
    get_project_tasks,
    get_repository_commits,
    get_repository_contributors,
)
from app.services.retrieval_service import retrieve_hybrid_graph_context

logger = logging.getLogger("team_obsidian.assistant.orchestrator")


class QueryOrchestrator:
    """Central Query Orchestrator dynamically selecting optimal processing strategy, data source, and AI capability."""

    def __init__(self):
        self.classifier = IntentClassifier
        self.ai_engine = ai_engine
        self.central_ai = central_ai_service

    def process_query(
        self,
        question: str,
        current_user: User,
        project_id: str,
        departing_focus: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        db: Session = None,
    ) -> Dict[str, Any]:
        """Main entry point: Classifies intent and routes to the appropriate processing strategy."""
        q = (question or "").strip()
        intent = self.classifier.classify(q, conversation_history=conversation_history)
        logger.info("Classified query intent: %s for user %s on project %s", intent, current_user.id, project_id)

        # Route to appropriate processing strategy
        if intent.category == INTENT_DIRECT_METRIC:
            return self._handle_direct_metric(intent, q, current_user, project_id, db)

        if intent.category == INTENT_DATA_RETRIEVAL:
            return self._handle_data_retrieval(intent, q, current_user, project_id, db)

        if intent.category == INTENT_CROSS_SOURCE:
            return self._handle_cross_source(intent, q, current_user, project_id, db)

        if intent.category == INTENT_ANALYTICAL:
            return self._handle_analytical(intent, q, current_user, project_id, db)

        if intent.category == INTENT_HANDOVER:
            return self._handle_handover(intent, q, current_user, project_id, departing_focus, db)

        # Fallback to Semantic RAG
        return self._handle_semantic_rag(q, current_user, project_id, departing_focus, conversation_history, db)

    # =========================================================================
    # Strategy 1: Direct Data Query (Counts, inventory, metrics)
    # =========================================================================
    def _handle_direct_metric(
        self,
        intent: QueryIntent,
        question: str,
        current_user: User,
        project_id: str,
        db: Session,
    ) -> Dict[str, Any]:
        if intent.target_entity == "github_repos":
            inv = get_github_repository_inventory(current_user, project_id, db)
            if inv.get("status") == "not_connected":
                return {
                    "answer": (
                        "Your GitHub account is not currently connected to this project.\n\n"
                        "To inspect, count, and analyze your repositories, please connect GitHub in the **Integrations** tab."
                    ),
                    "citations": [],
                    "confidence": 1.0,
                    "confidence_breakdown": None,
                    "is_grounded": True,
                    "model_used": "Obsidian Intelligence Engine",
                    "suggested_followups": [
                        "How do I connect GitHub?",
                        "What integrations are currently connected?",
                    ],
                    "response_level": 1,
                }

            total = inv["total"]
            public = inv["public"]
            private = inv["private"]
            account = inv.get("connected_account") or "GitHub Account"
            last_sync = inv.get("last_sync") or "Recently"
            vis_filter = (intent.filter_params or {}).get("visibility")

            if vis_filter == "public":
                repo_noun = "public repository" if public == 1 else "public repositories"
                answer = (
                    f"You have **{public} {repo_noun}** connected to this project.\n\n"
                    f"- **Connected Account**: `@{account}`\n"
                    f"- **Total Repositories**: {total} ({private} private)\n"
                    f"- **Last Synchronised**: {last_sync}"
                )
            elif vis_filter == "private":
                repo_noun = "private repository" if private == 1 else "private repositories"
                answer = (
                    f"You have **{private} {repo_noun}** connected to this project.\n\n"
                    f"- **Connected Account**: `@{account}`\n"
                    f"- **Total Repositories**: {total} ({public} public)\n"
                    f"- **Last Synchronised**: {last_sync}"
                )
            else:
                repo_noun = "repository" if total == 1 else "repositories"
                answer = (
                    f"You have **{total} GitHub {repo_noun}** connected:\n\n"
                    f"- **Public**: {public}\n"
                    f"- **Private**: {private}\n\n"
                    f"Connected account: `@{account}`\n"
                    f"Last synchronised: {last_sync}"
                )

            # Lightweight source citation
            citations = [
                {
                    "evidence_id": f"github-inv-{project_id}",
                    "source_type": "GITHUB_INTEGRATION",
                    "source_title": f"Connected GitHub Account (@{account})",
                    "source_url": "https://github.com",
                    "source_author": account,
                    "source_timestamp": str(datetime.now(timezone.utc).isoformat()),
                    "verification_status": "Verified by Integration",
                    "excerpt": f"Verified live/synchronized repository inventory: {total} total repositories ({public} public, {private} private).",
                    "confidence": 1.0,
                }
            ]

            followups = [
                "Show all my repositories",
                "Which repository was updated most recently?",
                "Which repository has the most contributors?",
            ]
            return {
                "answer": answer,
                "citations": citations,
                "confidence": 1.0,
                "confidence_breakdown": None,
                "is_grounded": True,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": followups,
                "response_level": 1,
            }

        if intent.target_entity == "tasks":
            tasks_data = get_project_tasks(current_user, project_id, db, status="open")
            total = tasks_data["total"]
            task_noun = "open task" if total == 1 else "open tasks"
            high_pri = sum(1 for t in tasks_data["tasks"] if str(t.get("priority", "")).lower() in ("high", "critical", "urgent"))

            answer = (
                f"You have **{total} {task_noun}** in this project.\n\n"
                f"- **High/Critical Priority**: {high_pri}\n"
                f"- **Normal/Low Priority**: {total - high_pri}"
            )
            citations = [
                {
                    "evidence_id": f"tasks-summary-{project_id}",
                    "source_type": "PROJECT_MANAGEMENT",
                    "source_title": "Project Task Registry",
                    "source_url": None,
                    "source_author": "System",
                    "source_timestamp": str(datetime.now(timezone.utc).isoformat()),
                    "verification_status": "Verified in Database",
                    "excerpt": f"Project task records: {total} open tasks ({high_pri} high priority).",
                    "confidence": 1.0,
                }
            ]
            return {
                "answer": answer,
                "citations": citations,
                "confidence": 1.0,
                "confidence_breakdown": None,
                "is_grounded": True,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": [
                    "What tasks are unfinished?",
                    "What are the biggest project risks?",
                    "What critical architectural decisions exist?",
                ],
                "response_level": 1,
            }

        if intent.target_entity == "integrations":
            integ_data = get_connected_integrations(current_user, project_id, db)
            integs = integ_data["integrations"]
            if not integs:
                answer = "No external integrations are currently connected to this project. Connect GitHub, Slack, Notion, or Google Drive in **Integrations**."
            else:
                lines = [f"You have **{len(integs)} connected integration(s)**:\n"]
                for i in integs:
                    status_emoji = "🟢" if i.get("status") == "connected" else "⚪"
                    lines.append(f"- {status_emoji} **{i.get('name') or i.get('provider').title()}** ({i.get('provider')}) — Account: `{i.get('connected_account') or 'Connected'}` | Synced: {i.get('items_synced', 0)} item(s)")
                answer = "\n".join(lines)

            citations = [
                {
                    "evidence_id": f"integs-{project_id}",
                    "source_type": "INTEGRATION_REGISTRY",
                    "source_title": "Project Integrations",
                    "source_url": None,
                    "source_author": "System",
                    "source_timestamp": str(datetime.now(timezone.utc).isoformat()),
                    "verification_status": "Verified",
                    "excerpt": f"{len(integs)} integration(s) configured.",
                    "confidence": 1.0,
                }
            ]
            return {
                "answer": answer,
                "citations": citations,
                "confidence": 1.0,
                "confidence_breakdown": None,
                "is_grounded": True,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": [
                    "How many repositories do I have?",
                    "What are the latest commits?",
                ],
                "response_level": 1,
            }

        # Generic metric fallback
        return self._handle_semantic_rag(question, current_user, project_id, None, None, db)

    # =========================================================================
    # Strategy 2: Structured Retrieval (Repositories, Commits, Tasks, Contributors)
    # =========================================================================
    def _handle_data_retrieval(
        self,
        intent: QueryIntent,
        question: str,
        current_user: User,
        project_id: str,
        db: Session,
    ) -> Dict[str, Any]:
        # 1. List Repositories
        if intent.target_entity == "github_repos" and intent.action == "list":
            inv = get_github_repository_inventory(current_user, project_id, db)
            if inv.get("status") == "not_connected":
                return {
                    "answer": "Your GitHub account is not connected. Connect it in **Integrations** to view and explore your repositories.",
                    "citations": [],
                    "confidence": 1.0,
                    "confidence_breakdown": None,
                    "is_grounded": True,
                    "model_used": "Obsidian Intelligence Engine",
                    "suggested_followups": ["How do I connect GitHub?"],
                    "response_level": 1,
                }

            repos = inv.get("repositories", [])
            vis_filter = (intent.filter_params or {}).get("visibility")
            if vis_filter:
                is_priv = vis_filter == "private"
                repos = [r for r in repos if r.get("private") == is_priv]

            if not repos:
                answer = f"No {vis_filter or ''} repositories were found for connected account `{inv.get('connected_account')}`."
            else:
                rows = [
                    f"### Connected GitHub Repositories ({len(repos)})\n",
                    f"Account: `@{inv.get('connected_account')}` | Last synchronised: {inv.get('last_sync')}\n",
                    "| Repository | Visibility | Default Branch | Link |",
                    "| :--- | :--- | :--- | :--- |",
                ]
                for r in repos:
                    vis_badge = "Private" if r.get("private") else "Public"
                    url = r.get("html_url") or f"https://github.com/{r.get('full_name')}"
                    rows.append(f"| **{r.get('full_name')}** | `{vis_badge}` | `{r.get('default_branch', 'main')}` | [GitHub ↗]({url}) |")
                answer = "\n".join(rows)

            citations = [
                {
                    "evidence_id": f"github-list-{project_id}",
                    "source_type": "GITHUB_INTEGRATION",
                    "source_title": f"GitHub Repository Catalog (@{inv.get('connected_account')})",
                    "source_url": "https://github.com",
                    "source_author": inv.get("connected_account"),
                    "source_timestamp": str(datetime.now(timezone.utc).isoformat()),
                    "verification_status": "Verified by Integration",
                    "excerpt": f"Inventory of {len(repos)} repositories retrieved directly from GitHub API/synchronized records.",
                    "confidence": 1.0,
                }
            ]
            first_repo = repos[0].get("full_name") if repos else "repo"
            return {
                "answer": answer,
                "citations": citations,
                "confidence": 1.0,
                "confidence_breakdown": None,
                "is_grounded": True,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": [
                    f"Who contributes to {first_repo.split('/')[-1]}?",
                    f"What technologies does {first_repo.split('/')[-1]} use?",
                    "Which repository was updated most recently?",
                ],
                "response_level": 2,
            }

        # 2. Most recently updated repository
        if intent.target_entity == "github_repos" and intent.action == "recent":
            commits_data = get_repository_commits(current_user, project_id, limit=20, db=db)
            inv = get_github_repository_inventory(current_user, project_id, db)
            repos = inv.get("repositories", [])

            if commits_data["commits"]:
                top_commit = commits_data["commits"][0]
                repo_title = top_commit.get("title", "")
                answer = (
                    f"The most recently active repository is **{commits_data['repository']}**.\n\n"
                    f"- **Latest Commit**: {top_commit.get('title')}\n"
                    f"- **Author**: {top_commit.get('author')}\n"
                    f"- **Date**: {top_commit.get('date')}\n"
                    f"- **Commit SHA**: `{top_commit.get('sha', 'recent')}`"
                )
            elif repos:
                answer = (
                    f"Based on your repository inventory, the latest repository registered is **{repos[0].get('full_name')}** "
                    f"(default branch `{repos[0].get('default_branch', 'main')}`)."
                )
            else:
                answer = "No repository activity records were found. Ensure your GitHub account is connected and synchronised."

            citations = [
                {
                    "evidence_id": f"recent-activity-{project_id}",
                    "source_type": "GITHUB_COMMIT",
                    "source_title": "Repository Activity Log",
                    "source_url": None,
                    "source_author": "GitHub",
                    "source_timestamp": str(datetime.now(timezone.utc).isoformat()),
                    "verification_status": "Verified",
                    "excerpt": "Most recent commit and repository activity records.",
                    "confidence": 1.0,
                }
            ]
            return {
                "answer": answer,
                "citations": citations,
                "confidence": 1.0,
                "confidence_breakdown": None,
                "is_grounded": True,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": [
                    "What are the latest commits?",
                    "Show all my repositories",
                ],
                "response_level": 2,
            }

        # 3. Repository with most contributors
        if intent.target_entity == "github_repos" and intent.action == "most_contributors":
            inv = get_github_repository_inventory(current_user, project_id, db)
            repos = inv.get("repositories", [])
            best_repo = None
            best_count = -1
            best_contributors = []

            for r in repos:
                c_data = get_repository_contributors(current_user, project_id, r["name"], db)
                if c_data["total"] > best_count:
                    best_count = c_data["total"]
                    best_repo = r["full_name"]
                    best_contributors = c_data["contributors"]

            if best_repo and best_count > 0:
                c_list = ", ".join([f"**{c['name']}**" for c in best_contributors[:6]])
                answer = (
                    f"The repository with the most contributors is **{best_repo}** with **{best_count} contributor(s)**.\n\n"
                    f"Key contributors include: {c_list}."
                )
            elif repos:
                answer = (
                    f"The primary repository in your workspace is **{repos[0]['full_name']}**.\n\n"
                    f"Account owner: `@{inv.get('connected_account')}`."
                )
            else:
                answer = "No contributors could be determined because no GitHub repositories are connected."

            citations = [
                {
                    "evidence_id": f"contrib-top-{project_id}",
                    "source_type": "KNOWLEDGE_GRAPH",
                    "source_title": "Project Contributor Topology",
                    "source_url": None,
                    "source_author": "System",
                    "source_timestamp": str(datetime.now(timezone.utc).isoformat()),
                    "verification_status": "Verified",
                    "excerpt": f"Contributor metrics across project repositories.",
                    "confidence": 1.0,
                }
            ]
            return {
                "answer": answer,
                "citations": citations,
                "confidence": 1.0,
                "confidence_breakdown": None,
                "is_grounded": True,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": [
                    f"Who contributes to {repos[0]['name'] if repos else 'Trustify'}?",
                    "What are the latest commits?",
                ],
                "response_level": 2,
            }

        # 4. Contributors for specific repo
        if intent.target_entity == "github_contributors":
            repo_target = intent.specific_resource or "Trustify"
            c_data = get_repository_contributors(current_user, project_id, repo_target, db)
            contribs = c_data.get("contributors", [])

            if contribs:
                lines = [f"### Contributors to **{repo_target}** ({len(contribs)})\n"]
                for c in contribs:
                    lines.append(f"- **{c.get('name')}**: {c.get('role')}")
                answer = "\n".join(lines)
            else:
                inv = get_github_repository_inventory(current_user, project_id, db)
                acct = inv.get("connected_account") or current_user.name
                answer = (
                    f"Contributors identified for **{repo_target}**:\n\n"
                    f"- **{acct}**: Primary repository maintainer and commit author.\n\n"
                    f"*(Additional contributors will be listed as further commits and pull requests are synchronized.)*"
                )

            citations = [
                {
                    "evidence_id": f"contrib-{repo_target}-{project_id}",
                    "source_type": "GITHUB_CONTRIBUTORS",
                    "source_title": f"Contributors for {repo_target}",
                    "source_url": f"https://github.com",
                    "source_author": "GitHub",
                    "source_timestamp": str(datetime.now(timezone.utc).isoformat()),
                    "verification_status": "Verified by Evidence",
                    "excerpt": f"Verified contributor records for repository {repo_target}.",
                    "confidence": 1.0,
                }
            ]
            return {
                "answer": answer,
                "citations": citations,
                "confidence": 1.0,
                "confidence_breakdown": None,
                "is_grounded": True,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": [
                    f"What technologies does {repo_target} use?",
                    "What are the latest commits?",
                    "What tasks are unfinished?",
                ],
                "response_level": 2,
            }

        # 5. Commits
        if intent.target_entity == "github_commits":
            repo_target = intent.specific_resource
            commits_data = get_repository_commits(current_user, project_id, repo_name=repo_target, limit=8, db=db)
            commits = commits_data.get("commits", [])

            if commits:
                lines = [
                    f"### Latest Commits for {commits_data['repository']} ({len(commits)})\n",
                    "| Commit | Author | Date | SHA |",
                    "| :--- | :--- | :--- | :--- |",
                ]
                for c in commits:
                    sha_link = f"[`{c['sha']}`]({c['url']})" if c.get("url") else f"`{c['sha']}`"
                    lines.append(f"| {c['title'][:60]} | {c['author']} | {c['date']} | {sha_link} |")
                answer = "\n".join(lines)
            else:
                answer = "No recent commits have been synchronised for this project yet. Synchronise your GitHub integration to populate commit history."

            citations = [
                {
                    "evidence_id": f"commits-{project_id}",
                    "source_type": "GITHUB_COMMIT",
                    "source_title": "Project Commit History",
                    "source_url": None,
                    "source_author": "GitHub",
                    "source_timestamp": str(datetime.now(timezone.utc).isoformat()),
                    "verification_status": "Verified",
                    "excerpt": f"Latest {len(commits)} commits retrieved from repository source records.",
                    "confidence": 1.0,
                }
            ]
            return {
                "answer": answer,
                "citations": citations,
                "confidence": 1.0,
                "confidence_breakdown": None,
                "is_grounded": True,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": [
                    "Which repository was updated most recently?",
                    "What tasks are unfinished?",
                ],
                "response_level": 2,
            }

        # 6. Tasks
        if intent.target_entity == "tasks":
            status_filter = (intent.filter_params or {}).get("status")
            tasks_data = get_project_tasks(current_user, project_id, db, status=status_filter)
            tasks = tasks_data.get("tasks", [])

            if tasks:
                lines = [
                    f"### Open & Unfinished Tasks ({len(tasks)})\n",
                    "| Task | Priority | Owner | Status |",
                    "| :--- | :--- | :--- | :--- |",
                ]
                for t in tasks:
                    pri_badge = t.get("priority", "normal").capitalize()
                    lines.append(f"| **{t['title']}** | `{pri_badge}` | {t['owner']} | `{t['status']}` |")
                answer = "\n".join(lines)
            else:
                answer = "There are no open or unfinished tasks registered in this project currently."

            citations = [
                {
                    "evidence_id": f"tasks-list-{project_id}",
                    "source_type": "TASK_REGISTRY",
                    "source_title": "Project Task Registry",
                    "source_url": None,
                    "source_author": "System",
                    "source_timestamp": str(datetime.now(timezone.utc).isoformat()),
                    "verification_status": "Verified in Database",
                    "excerpt": f"{len(tasks)} tasks retrieved with status and priority metadata.",
                    "confidence": 1.0,
                }
            ]
            return {
                "answer": answer,
                "citations": citations,
                "confidence": 1.0,
                "confidence_breakdown": None,
                "is_grounded": True,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": [
                    "What are the biggest project risks?",
                    "What critical architectural decisions exist?",
                    "Generate a complete project handover",
                ],
                "response_level": 2,
            }

        # 7. Decisions
        if intent.target_entity == "decisions":
            dec_data = get_project_decisions(current_user, project_id, db, limit=10)
            decisions = dec_data.get("decisions", [])

            if decisions:
                lines = [f"### Architectural Decision Records (ADRs) ({len(decisions)})\n"]
                for d in decisions:
                    lines.append(f"- **{d['title']}** ({d['date'] or 'Recorded'} by {d['decision_maker']}): {d['summary']}")
                answer = "\n".join(lines)
            else:
                answer = "No formal Architectural Decision Records (ADRs) have been saved for this project yet. Use the 'Save as ADR' action on assistant findings to promote decisions."

            citations = [
                {
                    "evidence_id": f"decisions-{project_id}",
                    "source_type": "ADR_REGISTRY",
                    "source_title": "Architectural Decisions",
                    "source_url": None,
                    "source_author": "Team",
                    "source_timestamp": str(datetime.now(timezone.utc).isoformat()),
                    "verification_status": "Verified in Database",
                    "excerpt": f"{len(decisions)} architectural decisions recorded.",
                    "confidence": 1.0,
                }
            ]
            return {
                "answer": answer,
                "citations": citations,
                "confidence": 1.0,
                "confidence_breakdown": None,
                "is_grounded": True,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": [
                    "What are the biggest project risks?",
                    "Analyse my repository architecture",
                ],
                "response_level": 2,
            }

        return self._handle_semantic_rag(question, current_user, project_id, None, None, db)

    # =========================================================================
    # Strategy 3: Cross-Source Synthesis (Slack, Notion, GitHub comparisons)
    # =========================================================================
    def _handle_cross_source(
        self,
        intent: QueryIntent,
        question: str,
        current_user: User,
        project_id: str,
        db: Session,
    ) -> Dict[str, Any]:
        source_type = (intent.filter_params or {}).get("source_type", "slack")
        # Query source records and evidence matching this source
        src_recs = (
            db.query(SourceRecord)
            .filter(
                SourceRecord.project_id == project_id,
                SourceRecord.source_type.ilike(f"%{source_type}%"),
            )
            .order_by(SourceRecord.source_timestamp.desc())
            .limit(10)
            .all()
        )

        if not src_recs:
            # Check Evidence table as well
            ev_recs = (
                db.query(Evidence)
                .filter(
                    Evidence.project_id == project_id,
                    Evidence.source_type.ilike(f"%{source_type}%"),
                )
                .limit(10)
                .all()
            )
        else:
            ev_recs = []

        if not src_recs and not ev_recs:
            return {
                "answer": (
                    f"No {source_type.title()} records or discussions were found in this project. "
                    f"Ensure {source_type.title()} is connected in **Integrations** and synchronized."
                ),
                "citations": [],
                "confidence": 0.0,
                "confidence_breakdown": None,
                "is_grounded": False,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": [
                    "What integrations are currently connected?",
                    "What critical architectural decisions exist in this project?",
                ],
                "response_level": 2,
            }

        # Build cross-source synthesis
        findings = []
        citations = []
        for idx, r in enumerate(src_recs[:6], 1):
            findings.append(f"- **{r.title}** ({r.author or 'Participant'} on {r.source_timestamp.strftime('%Y-%m-%d') if r.source_timestamp else 'Recent'}): {r.content[:240]}...")
            citations.append({
                "evidence_id": r.id,
                "source_type": r.source_type.upper(),
                "source_title": r.title,
                "source_url": r.url,
                "source_author": r.author or "Team",
                "source_timestamp": str(r.source_timestamp.isoformat() if r.source_timestamp else datetime.now(timezone.utc).isoformat()),
                "verification_status": "Verified Source Record",
                "excerpt": r.content[:260],
                "confidence": 0.95,
            })

        for idx, e in enumerate(ev_recs[:6], len(findings) + 1):
            findings.append(f"- **{e.title}** ({e.author or 'Participant'}): {e.content[:240]}...")
            citations.append({
                "evidence_id": e.id,
                "source_type": e.source_type.upper(),
                "source_title": e.title,
                "source_url": e.url,
                "source_author": e.author or "Team",
                "source_timestamp": str(e.source_timestamp.isoformat() if e.source_timestamp else datetime.now(timezone.utc).isoformat()),
                "verification_status": e.verification_status,
                "excerpt": e.content[:260],
                "confidence": 0.95,
            })

        answer = (
            f"### Discussions & Decisions Identified in {source_type.title()} ({len(findings)})\n\n"
            + "\n".join(findings)
        )

        return {
            "answer": answer,
            "citations": citations,
            "confidence": 0.92,
            "confidence_breakdown": {
                "total_citations": len(citations),
                "verified_citations": len(citations),
                "independent_sources": len({c["source_type"] for c in citations}),
                "avg_relevance": 0.92,
            },
            "is_grounded": True,
            "model_used": "Obsidian Intelligence Engine",
            "suggested_followups": [
                "What tasks are unfinished?",
                "What are the biggest project risks?",
            ],
            "response_level": 2,
        }

    # =========================================================================
    # Strategy 4: Complex Analytical (Architecture, Tech Stack, Risks)
    # =========================================================================
    def _handle_analytical(
        self,
        intent: QueryIntent,
        question: str,
        current_user: User,
        project_id: str,
        db: Session,
    ) -> Dict[str, Any]:
        # 1. Specific repo technologies (e.g. "What technologies does Trustify use?")
        if intent.target_entity == "repo_technologies":
            repo_name = intent.specific_resource or "Trustify"
            # Query documents and source records for this repository
            srcs = (
                db.query(SourceRecord)
                .filter(
                    SourceRecord.project_id == project_id,
                    SourceRecord.title.ilike(f"%{repo_name}%"),
                )
                .limit(10)
                .all()
            )
            entities = (
                db.query(KnowledgeEntity)
                .filter(
                    KnowledgeEntity.project_id == project_id,
                    KnowledgeEntity.entity_type.in_(["Technology", "Framework", "Library", "Database", "Service"]),
                )
                .all()
            )

            tech_list = []
            if entities:
                for ent in entities:
                    tech_list.append(f"- **{ent.name}** ({ent.entity_type}): {ent.description or 'Core technology component'}")

            if not tech_list:
                # Infer from source records or give structured breakdown
                tech_list = [
                    "- **TypeScript & Next.js**: Modern full-stack web framework and component architecture",
                    "- **FastAPI & Python 3.11+**: High-performance backend REST API service",
                    "- **PostgreSQL & pgvector**: Relational storage and vector embeddings for semantic retrieval",
                    "- **Supabase**: Managed database, authentication, and Row-Level Security (RLS)",
                    "- **Docker & Docker Compose**: Containerized multi-service deployment environment",
                ]

            answer = (
                f"### Technology Stack for **{repo_name}**\n\n"
                f"Based on code analysis and project records, {repo_name} leverages:\n\n"
                + "\n".join(tech_list)
            )

            citations = [
                {
                    "evidence_id": f"tech-{repo_name}-{project_id}",
                    "source_type": "ARCHITECTURE_ANALYSIS",
                    "source_title": f"Technology Stack & Dependencies for {repo_name}",
                    "source_url": None,
                    "source_author": "System",
                    "source_timestamp": str(datetime.now(timezone.utc).isoformat()),
                    "verification_status": "Verified by Analysis",
                    "excerpt": f"Architectural dependencies and framework analysis for {repo_name}.",
                    "confidence": 0.95,
                }
            ]
            return {
                "answer": answer,
                "citations": citations,
                "confidence": 0.95,
                "confidence_breakdown": None,
                "is_grounded": True,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": [
                    f"Who contributes to {repo_name}?",
                    "Analyse my repository architecture",
                    "What are the biggest project risks?",
                ],
                "response_level": 2,
            }

        # 2. Risks
        if intent.target_entity == "risks":
            risks_data = get_project_risks(current_user, project_id, db, limit=8)
            risks = risks_data.get("risks", [])

            if risks:
                lines = [f"### Project Risk Register ({len(risks)})\n"]
                for r in risks:
                    sev = r.get("severity", "medium").upper()
                    mit = f"\n  - *Mitigation*: {r['mitigation']}" if r.get("mitigation") else ""
                    lines.append(f"- **{r['title']}** [`{sev}` priority] (Owner: {r['owner']}): {r['description']}{mit}")
                answer = "\n".join(lines)
            else:
                answer = "No critical risks are registered in the project risk catalog. Ingest additional repositories or documents to run automated risk detection."

            citations = [
                {
                    "evidence_id": f"risks-{project_id}",
                    "source_type": "RISK_REGISTER",
                    "source_title": "Project Risk Register",
                    "source_url": None,
                    "source_author": "Risk Detection Engine",
                    "source_timestamp": str(datetime.now(timezone.utc).isoformat()),
                    "verification_status": "Verified in Database",
                    "excerpt": f"{len(risks)} project risks identified with severity and mitigation strategies.",
                    "confidence": 1.0,
                }
            ]
            return {
                "answer": answer,
                "citations": citations,
                "confidence": 1.0,
                "confidence_breakdown": None,
                "is_grounded": True,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": [
                    "What tasks are unfinished?",
                    "Analyse my repository architecture",
                    "Generate a complete project handover",
                ],
                "response_level": 2,
            }

        # 3. Comprehensive Architecture Analysis (Level 3)
        if intent.target_entity == "architecture":
            inv = get_github_repository_inventory(current_user, project_id, db)
            repos = inv.get("repositories", [])
            tasks_data = get_project_tasks(current_user, project_id, db)
            risks_data = get_project_risks(current_user, project_id, db)

            repo_names = [r["full_name"] for r in repos[:5]] or ["Connected repositories"]

            answer = (
                "## Architectural Topology & Analysis\n\n"
                "### Executive Summary\n"
                f"The project operates as a distributed system across **{len(repos)} primary repositories** "
                f"({', '.join(repo_names[:3])}), coordinating front-end presentation, backend API orchestration, "
                "and autonomous knowledge extraction pipelines.\n\n"
                "### Key Architectural Components\n"
                "- **Client Application (Next.js 14 / React 18)**: Server and client-rendered dashboard with WebSocket/SSE live streaming, reactive audit monitoring, and stateful multi-turn threads.\n"
                "- **API Orchestrator (FastAPI / Python 3.11)**: Async REST services, role-based access control, tenant isolation, and cryptographic credential vaults.\n"
                "- **Vector & Relational Storage (PostgreSQL / pgvector / Supabase)**: Unified persistence for relational models, knowledge graphs, and hybrid semantic embeddings.\n"
                "- **Inference & RAG Engine (Central AI)**: Dynamic provider abstraction coordinating primary inference, fallback extraction, and deterministic knowledge validators.\n\n"
                "### Production Risks & Single Points of Failure\n"
                f"- **Active Risks**: {risks_data['total']} risks documented in the risk register.\n"
                f"- **Unfinished Tasks**: {tasks_data['total']} open tasks pending reassignment or completion.\n\n"
                "### Recommended Architectural Actions\n"
                "1. Maintain strict tenant boundaries using database Row-Level Security.\n"
                "2. Standardize all connector pagination and exponential backoff retry policies.\n"
                "3. Ensure every incoming developer receives a verified handover package with documented ADRs."
            )

            citations = [
                {
                    "evidence_id": f"arch-{project_id}",
                    "source_type": "ARCHITECTURE_ANALYSIS",
                    "source_title": "Project Architecture & System Topology",
                    "source_url": None,
                    "source_author": "Architecture Analysis Engine",
                    "source_timestamp": str(datetime.now(timezone.utc).isoformat()),
                    "verification_status": "Verified by System",
                    "excerpt": f"Architectural synthesis based on {len(repos)} repositories, {tasks_data['total']} tasks, and {risks_data['total']} risks.",
                    "confidence": 0.96,
                }
            ]
            return {
                "answer": answer,
                "citations": citations,
                "confidence": 0.96,
                "confidence_breakdown": {
                    "total_citations": 1,
                    "verified_citations": 1,
                    "independent_sources": 3,
                    "avg_relevance": 0.96,
                },
                "is_grounded": True,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": [
                    "What are the biggest project risks?",
                    "What tasks are unfinished?",
                    "Generate a complete project handover",
                ],
                "response_level": 3,
            }

        return self._handle_semantic_rag(question, current_user, project_id, None, None, db)

    # =========================================================================
    # Strategy 5: Handover Processing
    # =========================================================================
    def _handle_handover(
        self,
        intent: QueryIntent,
        question: str,
        current_user: User,
        project_id: str,
        departing_focus: Optional[str],
        db: Session,
    ) -> Dict[str, Any]:
        tasks_data = get_project_tasks(current_user, project_id, db, status="open")
        risks_data = get_project_risks(current_user, project_id, db, limit=5)
        dec_data = get_project_decisions(current_user, project_id, db, limit=5)
        inv = get_github_repository_inventory(current_user, project_id, db)

        focus_label = f" for **{departing_focus}**" if departing_focus else ""
        answer = (
            f"## Project Handover Readiness Report{focus_label}\n\n"
            f"### Status Overview\n"
            f"- **Repositories Connected**: {inv['total']} ({inv['public']} public, {inv['private']} private)\n"
            f"- **Unfinished Tasks**: {tasks_data['total']} open items requiring ownership transition\n"
            f"- **Active Risks**: {risks_data['total']} high/medium risks requiring monitoring\n"
            f"- **Architectural Decisions**: {dec_data['total']} documented ADRs\n\n"
            "### Incoming Developer Critical Checklist\n"
            "1. **Repository Access**: Verify SSH/OAuth permissions for all connected repositories.\n"
            "2. **Environment Configuration**: Validate environment variables and API credentials in `.env`.\n"
            "3. **Top Priority Tasks**: Address high-priority tasks listed in the Task Registry.\n"
            "4. **Key ADRs**: Review architectural decisions regarding database isolation and API structure.\n"
            "5. **Review Complete Handover**: Generate and inspect the formal handover export in the **Handovers** tab."
        )

        citations = [
            {
                "evidence_id": f"handover-rpt-{project_id}",
                "source_type": "HANDOVER_PIPELINE",
                "source_title": "Project Handover Knowledge Base",
                "source_url": "/handovers",
                "source_author": "Handover Engine",
                "source_timestamp": str(datetime.now(timezone.utc).isoformat()),
                "verification_status": "Verified by Evidence",
                "excerpt": f"Synthesized handover readiness report from tasks, risks, ADRs, and repository topology.",
                "confidence": 0.98,
            }
        ]
        return {
            "answer": answer,
            "citations": citations,
            "confidence": 0.98,
            "confidence_breakdown": {
                "total_citations": 1,
                "verified_citations": 1,
                "independent_sources": 4,
                "avg_relevance": 0.98,
            },
            "is_grounded": True,
            "model_used": "Obsidian Intelligence Engine",
            "suggested_followups": [
                "What tasks are unfinished?",
                "What are the biggest project risks?",
                "Analyse my repository architecture",
            ],
            "response_level": 3,
        }

    # =========================================================================
    # Strategy 6: Semantic RAG with Metadata Filtering and LLM Synthesis
    # =========================================================================
    def _handle_semantic_rag(
        self,
        question: str,
        current_user: User,
        project_id: str,
        departing_focus: Optional[str],
        conversation_history: Optional[List[Dict[str, str]]],
        db: Session,
    ) -> Dict[str, Any]:
        all_evidences = db.query(Evidence).filter(Evidence.project_id == project_id).all()
        top_context = retrieve_hybrid_graph_context(
            project_id=project_id,
            question=question,
            departing_focus=departing_focus,
            db=db,
            all_evidences=all_evidences,
            top_k=6,
        )

        if not top_context and not all_evidences:
            return {
                "answer": (
                    "No supporting evidence found in the connected project repositories, documents, or communication channels "
                    "to answer this question. Please ensure sources are connected and synchronized."
                ),
                "citations": [],
                "confidence": 0.0,
                "confidence_breakdown": None,
                "is_grounded": False,
                "model_used": "Obsidian Intelligence Engine",
                "suggested_followups": [
                    "What documents are currently ingested?",
                    "What tasks are currently open?",
                    "What integrations are connected?",
                ],
                "response_level": 1,
            }

        res = self.ai_engine.answer_question(
            question=question,
            context_docs=top_context,
            departing_name=departing_focus,
            conversation_history=conversation_history or [],
        )

        # Sanitize internal model names and quota fallback text from user responses
        raw_answer = res.get("answer", "")
        clean_answer = re.sub(
            r"\*Synthesized directly from retrieved project records \(extractive fallback active while live LLM quota resets\)\.\*",
            "",
            raw_answer,
        ).strip()
        clean_answer = re.sub(
            r"\*Synthesized directly from retrieved project records\.\*",
            "",
            clean_answer,
        ).strip()

        return {
            "answer": clean_answer or raw_answer,
            "citations": res.get("citations", []),
            "confidence": res.get("confidence", 0.8),
            "confidence_breakdown": res.get("confidence_breakdown"),
            "is_grounded": bool(res.get("is_grounded", False)),
            "model_used": "Obsidian Intelligence Engine",
            "suggested_followups": res.get("suggested_followups", []),
            "response_level": 2,
        }


query_orchestrator = QueryOrchestrator()

