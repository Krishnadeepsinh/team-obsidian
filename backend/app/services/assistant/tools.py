from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.security import decrypt_credentials
from app.models.evidence import Evidence
from app.models.handover import Handover
from app.models.integration import Document, Integration, SourceRecord
from app.models.knowledge import Decision, Dependency, KnowledgeEntity, KnowledgeGap, RiskItem, TaskItem
from app.models.workspace import Project, User
from app.services.connectors.base import ConnectorError
from app.services.connectors.github_connector import GitHubConnector

logger = logging.getLogger("team_obsidian.assistant.tools")


def _get_project_github_integration(
    current_user: User,
    project_id: str,
    db: Session,
) -> Optional[Integration]:
    """Find authorized GitHub integration for project or user."""
    integ = (
        db.query(Integration)
        .filter(
            Integration.project_id == project_id,
            Integration.provider == "github",
        )
        .first()
    )
    if not integ and current_user:
        # Check org-level integration accessible to user
        integ = (
            db.query(Integration)
            .filter(
                Integration.provider == "github",
                Integration.user_id == current_user.id,
            )
            .first()
        )
    return integ


def get_github_repository_inventory(
    current_user: User,
    project_id: str,
    db: Session,
) -> Dict[str, Any]:
    """Retrieve verified repository inventory directly from GitHub API or synchronized source records."""
    integ = _get_project_github_integration(current_user, project_id, db)
    if not integ or integ.status == "disconnected":
        return {
            "status": "not_connected",
            "message": "Your GitHub account is not connected. Connect it in Integrations to view and analyze your repositories.",
            "total": 0,
            "public": 0,
            "private": 0,
            "repositories": [],
        }

    creds = decrypt_credentials(integ.credentials)
    token = creds.get("access_token") or creds.get("token") or integ.config.get("token") if integ.config else None

    repos: List[Dict[str, Any]] = []
    seen: set[str] = set()

    # 1. Try Live GitHub API
    if token:
        try:
            connector = GitHubConnector(token=token)
            api_repos = connector.list_repositories(max_pages=5)
            for r in api_repos:
                full_name = r.get("full_name")
                if full_name and full_name not in seen:
                    seen.add(full_name)
                    repos.append({
                        "name": full_name.split("/")[-1],
                        "full_name": full_name,
                        "private": bool(r.get("private", False)),
                        "default_branch": r.get("default_branch", "main"),
                        "html_url": r.get("html_url") or f"https://github.com/{full_name}",
                    })
        except Exception as exc:
            logger.warning("Live GitHub repository query failed (%s); reading synchronized records", exc)

    # 2. If API was unavailable or had zero return, read synchronized records from database
    if not repos:
        # Check SourceRecords of type github_repository or github_repo
        src_recs = (
            db.query(SourceRecord)
            .filter(
                SourceRecord.project_id == project_id,
                SourceRecord.source_type.in_(["github_repository", "github_repo", "github_commit", "github_pr"]),
            )
            .all()
        )
        for sr in src_recs:
            repo_name = (sr.metadata_json or {}).get("repository") or (sr.raw_payload or {}).get("repository")
            if not repo_name and "/" in (sr.title or ""):
                parts = sr.title.split()
                for p in parts:
                    if "/" in p and not p.startswith("http"):
                        repo_name = p.strip("()[]:,")
                        break
            if repo_name and repo_name not in seen:
                seen.add(repo_name)
                is_priv = bool((sr.metadata_json or {}).get("private", False))
                repos.append({
                    "name": repo_name.split("/")[-1],
                    "full_name": repo_name,
                    "private": is_priv,
                    "default_branch": (sr.metadata_json or {}).get("default_branch", "main"),
                    "html_url": f"https://github.com/{repo_name}",
                })

        # Also check configured targets in integration config
        configured_repos = (integ.config or {}).get("repos") or (integ.config or {}).get("selected_repos") or []
        for cr in configured_repos:
            if cr and cr not in seen:
                seen.add(cr)
                repos.append({
                    "name": cr.split("/")[-1],
                    "full_name": cr,
                    "private": False,
                    "default_branch": "main",
                    "html_url": f"https://github.com/{cr}",
                })

    total = len(repos)
    private_count = sum(1 for r in repos if r.get("private"))
    public_count = total - private_count

    last_sync_str = "Recently"
    if integ.last_sync:
        last_sync_str = integ.last_sync.strftime("%d %B %Y at %H:%M UTC")

    return {
        "status": "connected",
        "connected_account": integ.connected_account or "GitHub Account",
        "total": total,
        "public": public_count,
        "private": private_count,
        "repositories": repos,
        "last_sync": last_sync_str,
    }


def get_repository_contributors(
    current_user: User,
    project_id: str,
    repo_name: str,
    db: Session,
) -> Dict[str, Any]:
    """Retrieve actual contributors for a specific repository from synchronized knowledge graph, commits, or GitHub API."""
    integ = _get_project_github_integration(current_user, project_id, db)
    norm_name = repo_name.strip().lower()

    # 1. Search KnowledgeEntity records (Person entities linked to repository)
    people = (
        db.query(KnowledgeEntity)
        .filter(
            KnowledgeEntity.project_id == project_id,
            KnowledgeEntity.entity_type == "Person",
        )
        .all()
    )
    matching_contributors = []
    for p in people:
        desc = (p.description or "").lower()
        if norm_name in desc or any(w in desc for w in norm_name.split("/")):
            matching_contributors.append({
                "name": p.name,
                "role": desc[:120],
            })

    # 2. Check SourceRecord authors for this repository
    src_authors = (
        db.query(SourceRecord.author)
        .filter(
            SourceRecord.project_id == project_id,
            SourceRecord.author.isnot(None),
        )
        .distinct()
        .all()
    )
    for (author,) in src_authors:
        if author and author not in ("Unknown", "GitHub Author"):
            if not any(c["name"] == author for c in matching_contributors):
                matching_contributors.append({
                    "name": author,
                    "role": "Active code committer and contributor",
                })

    # 3. Live GitHub API query if connected
    if not matching_contributors and integ:
        creds = decrypt_credentials(integ.credentials)
        token = creds.get("access_token") or creds.get("token")
        if token:
            try:
                conn = GitHubConnector(token=token)
                target = repo_name if "/" in repo_name else f"{integ.connected_account}/{repo_name}"
                res = conn._request_with_retry("GET", f"{conn.base_url}/repos/{target}/contributors", headers=conn.headers, params={"per_page": 20})
                if res.status_code == 200:
                    for u in res.json():
                        matching_contributors.append({
                            "name": u.get("login"),
                            "role": f"{u.get('contributions', 0)} commit(s)",
                        })
            except Exception as e:
                logger.warning("GitHub live contributors check failed: %s", e)

    return {
        "repository": repo_name,
        "contributors": matching_contributors,
        "total": len(matching_contributors),
    }


def get_repository_commits(
    current_user: User,
    project_id: str,
    repo_name: Optional[str] = None,
    limit: int = 10,
    db: Session = None,
) -> Dict[str, Any]:
    """Retrieve latest commits from database or live GitHub."""
    query = (
        db.query(SourceRecord)
        .filter(
            SourceRecord.project_id == project_id,
            SourceRecord.source_type.in_(["github_commit", "gitlab_commit", "commit"]),
        )
        .order_by(SourceRecord.source_timestamp.desc())
    )
    if repo_name:
        norm = repo_name.lower()
        query = query.filter(SourceRecord.title.ilike(f"%{norm}%"))

    recs = query.limit(limit).all()
    commits = [
        {
            "title": r.title,
            "author": r.author or "Unknown",
            "date": r.source_timestamp.strftime("%Y-%m-%d %H:%M") if r.source_timestamp else "Recent",
            "url": r.url,
            "sha": (r.metadata_json or {}).get("sha", r.external_id[:8]),
        }
        for r in recs
    ]
    return {
        "repository": repo_name or "All connected repositories",
        "commits": commits,
        "total": len(commits),
    }


def get_project_tasks(
    current_user: User,
    project_id: str,
    db: Session,
    status: Optional[str] = "open",
) -> Dict[str, Any]:
    """Retrieve actual tasks from database."""
    query = db.query(TaskItem).filter(TaskItem.project_id == project_id)
    if status:
        query = query.filter(TaskItem.status == status)

    tasks = query.order_by(TaskItem.priority.desc(), TaskItem.created_at.desc()).all()
    return {
        "total": len(tasks),
        "status_filter": status,
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "owner": t.owner or "Unassigned",
                "priority": t.priority,
                "status": t.status,
                "deadline": t.deadline,
            }
            for t in tasks
        ],
    }


def get_project_decisions(
    current_user: User,
    project_id: str,
    db: Session,
    limit: int = 10,
) -> Dict[str, Any]:
    """Retrieve actual architectural decisions from database."""
    decisions = (
        db.query(Decision)
        .filter(Decision.project_id == project_id)
        .order_by(Decision.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "total": len(decisions),
        "decisions": [
            {
                "id": d.id,
                "title": d.title,
                "summary": d.summary,
                "decision_maker": d.decision_maker or "Team",
                "date": d.date or (d.created_at.strftime("%Y-%m-%d") if d.created_at else None),
            }
            for d in decisions
        ],
    }


def get_project_risks(
    current_user: User,
    project_id: str,
    db: Session,
    limit: int = 10,
) -> Dict[str, Any]:
    """Retrieve actual project risks from database."""
    risks = (
        db.query(RiskItem)
        .filter(RiskItem.project_id == project_id)
        .order_by(RiskItem.severity.desc())
        .limit(limit)
        .all()
    )
    return {
        "total": len(risks),
        "risks": [
            {
                "id": r.id,
                "title": r.title,
                "description": r.description,
                "severity": r.severity,
                "likelihood": r.likelihood,
                "owner": r.owner or "Unassigned",
                "mitigation": r.mitigation_strategy,
            }
            for r in risks
        ],
    }


def get_connected_integrations(
    current_user: User,
    project_id: str,
    db: Session,
) -> Dict[str, Any]:
    """Retrieve connected services for this project."""
    integs = db.query(Integration).filter(Integration.project_id == project_id).all()
    return {
        "total": len(integs),
        "integrations": [
            {
                "provider": i.provider,
                "name": i.name,
                "status": i.status,
                "connected_account": i.connected_account,
                "items_synced": i.items_synced,
                "last_sync": i.last_sync.strftime("%Y-%m-%d %H:%M UTC") if i.last_sync else None,
            }
            for i in integs
        ],
    }

