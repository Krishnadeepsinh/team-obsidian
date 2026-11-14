from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.permissions import get_user_accessible_project_ids, verify_project_access
from app.core.security import get_current_user
from app.models.evidence import Evidence
from app.models.handover import Handover
from app.models.integration import Document, Integration, SourceRecord
from app.models.knowledge import Decision, Dependency, KnowledgeEntity, KnowledgeGap, RiskItem, TaskItem
from app.models.workspace import ActivityLog, Project, User

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _last_six_months_buckets() -> OrderedDict:
    now = datetime.now(timezone.utc)
    buckets: OrderedDict[str, Dict[str, Any]] = OrderedDict()
    year = now.year
    month = now.month
    keys = []
    for _ in range(6):
        keys.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    keys.reverse()
    for y, m in keys:
        dt = datetime(y, m, 1, tzinfo=timezone.utc)
        buckets[f"{y:04d}-{m:02d}"] = {
            "month": dt.strftime("%b"),
            "ingested": 0,
            "verified": 0,
            "handovers": 0,
        }
    return buckets


@router.get("/stats")
def get_dashboard_stats(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return real database statistics aggregated strictly across the user's permitted projects."""
    if project_id:
        verify_project_access(project_id, current_user, db)
        p_ids = [project_id]
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)

    if not p_ids:
        empty_trend = list(_last_six_months_buckets().values())
        return {
            "metrics": {
                "projects": 0,
                "connected_sources": 0,
                "total_sources": 0,
                "knowledge_items": 0,
                "decisions": 0,
                "open_tasks": 0,
                "completed_tasks": 0,
                "unresolved_risks": 0,
                "critical_risks": 0,
                "pending_reviews": 0,
                "verified_evidences": 0,
                "handovers": 0,
                "approved_handovers": 0,
                "documents": 0,
                "source_records": 0,
                "dependencies": 0,
                "knowledge_gaps": 0,
            },
            "active_handover": None,
            "recent_decisions": [],
            "upcoming_tasks": [],
            "integrations": [],
            "distribution": [],
            "activity_trend": empty_trend,
        }

    proj_query = db.query(Project).filter(Project.id.in_(p_ids))
    integ_query = db.query(Integration).filter(Integration.project_id.in_(p_ids))
    ent_query = db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id.in_(p_ids))
    dec_query = db.query(Decision).filter(Decision.project_id.in_(p_ids))
    task_query = db.query(TaskItem).filter(TaskItem.project_id.in_(p_ids))
    risk_query = db.query(RiskItem).filter(RiskItem.project_id.in_(p_ids))
    dep_query = db.query(Dependency).filter(Dependency.project_id.in_(p_ids))
    gap_query = db.query(KnowledgeGap).filter(KnowledgeGap.project_id.in_(p_ids))
    ev_query = db.query(Evidence).filter(Evidence.project_id.in_(p_ids))
    ho_query = db.query(Handover).filter(Handover.project_id.in_(p_ids))
    doc_query = db.query(Document).filter(Document.project_id.in_(p_ids))
    rec_query = db.query(SourceRecord).filter(SourceRecord.project_id.in_(p_ids))

    total_projects = 1 if project_id else len(p_ids)

    integrations = integ_query.all()
    integrations_list = [
        {
            "id": i.id,
            "provider": i.provider,
            "name": i.name,
            "status": i.status,
            "auth_status": getattr(i, "auth_status", "unverified"),
            "connected_account": getattr(i, "connected_account", None),
            "items_synced": i.items_synced,
            "last_sync": i.last_sync.isoformat() if i.last_sync else None,
        }
        for i in integrations
    ]
    connected_sources = sum(1 for i in integrations if i.status == "connected")
    total_sources = len(integrations)

    counts_row = db.query(
        db.query(func.count(KnowledgeEntity.id)).filter(KnowledgeEntity.project_id.in_(p_ids)).as_scalar(),
        db.query(func.count(Decision.id)).filter(Decision.project_id.in_(p_ids)).as_scalar(),
        db.query(func.count(Dependency.id)).filter(Dependency.project_id.in_(p_ids)).as_scalar(),
        db.query(func.count(KnowledgeGap.id)).filter(KnowledgeGap.project_id.in_(p_ids)).as_scalar(),
        db.query(func.count(Document.id)).filter(Document.project_id.in_(p_ids)).as_scalar(),
        db.query(func.count(SourceRecord.id)).filter(SourceRecord.project_id.in_(p_ids)).as_scalar(),
    ).first() or (0, 0, 0, 0, 0, 0)

    total_entities, total_decisions, total_dependencies, total_gaps, total_documents, total_source_records = counts_row

    task_counts = dict(
        db.query(TaskItem.status, func.count(TaskItem.id))
        .filter(TaskItem.project_id.in_(p_ids))
        .group_by(TaskItem.status)
        .all()
    )
    completed_tasks = task_counts.get("completed", 0)
    open_tasks = sum(c for s, c in task_counts.items() if s != "completed")

    risk_stats = db.query(
        func.count(case((RiskItem.status != "resolved", 1))),
        func.count(case((RiskItem.severity == "critical", 1))),
    ).filter(RiskItem.project_id.in_(p_ids)).first() or (0, 0)
    unresolved_risks = risk_stats[0] or 0
    critical_risks = risk_stats[1] or 0

    verified_statuses = ["Verified", "Verified by Reviewer", "Supported by Evidence"]
    pending_statuses = ["Needs Review", "Needs Human Verification", "Draft / AI Suggested", "Uncertain"]
    ev_stats = db.query(
        func.count(case((Evidence.verification_status.in_(pending_statuses), 1))),
        func.count(case((Evidence.verification_status.in_(verified_statuses), 1))),
    ).filter(Evidence.project_id.in_(p_ids)).first() or (0, 0)
    pending_reviews = ev_stats[0] or 0
    verified_evidences = ev_stats[1] or 0

    ho_stats = db.query(
        func.count(Handover.id),
        func.count(case((Handover.status.in_(["approved", "acknowledged", "published"]), 1))),
    ).filter(Handover.project_id.in_(p_ids)).first() or (0, 0)
    total_handovers = ho_stats[0] or 0
    approved_handovers = ho_stats[1] or 0

    knowledge_items_total = total_entities + total_documents + total_source_records

    decisions_list = []
    if total_decisions > 0:
        recent_decisions = dec_query.order_by(Decision.created_at.desc()).limit(5).all()
        decisions_list = [
            {
                "id": d.id,
                "title": d.title,
                "decision_maker": d.decision_maker,
                "date": d.date,
                "status": d.status,
                "verification_status": getattr(d, "verification_status", "Needs Human Verification"),
                "component": d.component,
                "confidence": d.confidence,
            }
            for d in recent_decisions
        ]

    tasks_list = []
    if open_tasks > 0:
        upcoming_tasks = task_query.filter(TaskItem.status != "completed").order_by(TaskItem.deadline.asc()).limit(5).all()
        tasks_list = [
            {
                "id": t.id,
                "title": t.title,
                "owner": t.owner,
                "priority": t.priority,
                "status": t.status,
                "deadline": t.deadline,
                "is_departing": t.is_departing_owner,
                "suggested_reassignment": t.suggested_reassignment,
            }
            for t in upcoming_tasks
        ]

    distribution = [
        {"category": "Decisions", "count": total_decisions, "fill": "#7C3AED"},
        {"category": "Tasks", "count": open_tasks + completed_tasks, "fill": "#38BDF8"},
        {"category": "Technical", "count": total_entities, "fill": "#6366F1"},
        {"category": "Dependencies", "count": total_dependencies, "fill": "#C084FC"},
        {"category": "Risks", "count": unresolved_risks, "fill": "#F472B6"},
        {"category": "Others", "count": total_documents + total_gaps, "fill": "#F59E0B"},
    ]

    # Real monthly aggregation from database timestamps (filtered to relevant 6 months window)
    buckets = _last_six_months_buckets()
    now = datetime.now(timezone.utc)
    cutoff_year = now.year
    cutoff_month = now.month - 5
    if cutoff_month <= 0:
        cutoff_month += 12
        cutoff_year -= 1
    six_months_ago = datetime(cutoff_year, cutoff_month, 1, tzinfo=timezone.utc)

    if total_source_records > 0:
        for (ts,) in rec_query.filter(SourceRecord.ingested_at >= six_months_ago).with_entities(SourceRecord.ingested_at).all():
            if ts:
                key = ts.strftime("%Y-%m")
                if key in buckets:
                    buckets[key]["ingested"] += 1

    if total_documents > 0:
        for (ts,) in doc_query.filter(Document.created_at >= six_months_ago).with_entities(Document.created_at).all():
            if ts:
                key = ts.strftime("%Y-%m")
                if key in buckets:
                    buckets[key]["ingested"] += 1

    if verified_evidences > 0:
        for (ts,) in ev_query.filter(Evidence.verification_status.in_(verified_statuses), Evidence.created_at >= six_months_ago).with_entities(Evidence.created_at).all():
            if ts:
                key = ts.strftime("%Y-%m")
                if key in buckets:
                    buckets[key]["verified"] += 1

    if total_handovers > 0:
        for (ts,) in ho_query.filter(Handover.created_at >= six_months_ago).with_entities(Handover.created_at).all():
            if ts:
                key = ts.strftime("%Y-%m")
                if key in buckets:
                    buckets[key]["handovers"] += 1
    activity_trend = list(buckets.values())

    latest_handover = ho_query.order_by(Handover.updated_at.desc()).first() if total_handovers > 0 else None
    active_handover_info = None
    if latest_handover:
        proj = db.query(Project).filter(Project.id == latest_handover.project_id).first()
        sections = latest_handover.sections or []
        verified_sections = sum(1 for s in sections if s.is_verified)
        completion = round(verified_sections / len(sections), 2) if sections else 0.0
        active_handover_info = {
            "id": latest_handover.id,
            "title": latest_handover.title,
            "project_name": proj.name if proj else "Workspace",
            "departing_employee": latest_handover.departing_employee_name,
            "incoming_employee": latest_handover.incoming_employee_name,
            "status": latest_handover.status,
            "target_date": getattr(latest_handover, "target_date", None) or (proj.target_handover_date if proj else None),
            "completion_progress": completion,
            "confidence": latest_handover.overall_confidence,
        }
    elif total_projects > 0:
        latest_project = proj_query.order_by(Project.created_at.desc()).first()
        if latest_project:
            active_handover_info = {
                "id": None,
                "title": latest_project.name,
                "project_name": latest_project.name,
                "departing_employee": None,
                "incoming_employee": None,
                "status": "active",
                "target_date": getattr(latest_project, "target_handover_date", None),
                "completion_progress": None,
                "confidence": None,
            }

    return {
        "metrics": {
            "projects": total_projects,
            "connected_sources": connected_sources,
            "total_sources": total_sources,
            "knowledge_items": knowledge_items_total,
            "decisions": total_decisions,
            "open_tasks": open_tasks,
            "completed_tasks": completed_tasks,
            "unresolved_risks": unresolved_risks,
            "critical_risks": critical_risks,
            "pending_reviews": pending_reviews,
            "verified_evidences": verified_evidences,
            "handovers": total_handovers,
            "approved_handovers": approved_handovers,
            "documents": total_documents,
            "source_records": total_source_records,
            "dependencies": total_dependencies,
            "knowledge_gaps": total_gaps,
        },
        "active_handover": active_handover_info,
        "recent_decisions": decisions_list,
        "upcoming_tasks": tasks_list,
        "integrations": integrations_list,
        "distribution": distribution,
        "activity_trend": activity_trend,
    }


@router.get("/activity")
def get_dashboard_activity(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    if project_id:
        verify_project_access(project_id, current_user, db)
        p_ids = [project_id]
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)

    query = db.query(ActivityLog)
    if p_ids:
        query = query.filter((ActivityLog.project_id.in_(p_ids)) | (ActivityLog.user_id == current_user.id))
    else:
        query = query.filter(ActivityLog.user_id == current_user.id)

    logs = query.order_by(ActivityLog.created_at.desc()).limit(20).all()
    return [
        {
            "id": l.id,
            "action": l.action,
            "entity_type": l.entity_type,
            "entity_id": l.entity_id,
            "details": l.details,
            "timestamp": l.created_at.isoformat(),
        }
        for l in logs
    ]
