from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_effective_project, get_user_accessible_project_ids, verify_project_access
from app.core.security import get_current_user
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
from app.models.workspace import User
from app.services.drift_detector import scan_project_for_drift

router = APIRouter(prefix="/knowledge", tags=["Knowledge Intelligence"])


@router.get("/explorer")
def explore_knowledge(
    project_id: Optional[str] = None,
    category: Optional[str] = Query(None),
    search: Optional[str] = None,
    source_type: Optional[str] = None,
    employee: Optional[str] = None,
    verification_status: Optional[str] = None,
    min_confidence: Optional[float] = 0.0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    if project_id:
        verify_project_access(project_id, current_user, db)
        p_ids = [project_id]
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)

    if not p_ids:
        return []

    s_lower = search.strip().lower() if search and search.strip() else None
    emp_lower = employee.strip().lower() if employee and employee.strip() else None
    vs_lower = verification_status.strip().lower() if verification_status and verification_status.strip().lower() != "all" else None

    def _status_matches(raw_vstat: Optional[str]) -> bool:
        if not vs_lower:
            return True
        actual = (raw_vstat or "").strip().lower()
        if vs_lower in ("verified", "verified by reviewer"):
            return actual in ("verified", "verified by reviewer")
        return actual == vs_lower

    if not category or category.lower() in ["all", "decisions"]:
        for d in db.query(Decision).filter(Decision.project_id.in_(p_ids)).all():
            if min_confidence and d.confidence < min_confidence:
                continue
            if emp_lower and emp_lower not in (d.decision_maker or "").lower():
                continue
            vstat = getattr(d, "verification_status", "Needs Human Verification")
            if not _status_matches(vstat):
                continue
            if s_lower and s_lower not in d.title.lower() and s_lower not in d.summary.lower():
                continue
            items.append({
                "id": d.id,
                "project_id": d.project_id,
                "category": "Decisions",
                "title": d.title,
                "subtitle": f"Decided by {d.decision_maker} on {d.date}",
                "content": d.summary,
                "summary": d.summary,
                "reasoning": d.reasoning,
                "owner": d.decision_maker,
                "date": d.date,
                "status": d.status,
                "verification_status": vstat,
                "confidence": d.confidence,
                "component": d.component,
                "evidence_ids": d.evidence_ids or [],
                "tags": ["ADR", d.decision_type],
            })

    if not category or category.lower() in ["all", "tasks", "responsibilities"]:
        for t in db.query(TaskItem).filter(TaskItem.project_id.in_(p_ids)).all():
            if min_confidence and t.confidence < min_confidence:
                continue
            if emp_lower and emp_lower not in (t.owner or "").lower():
                continue
            vstat = getattr(t, "verification_status", "Needs Human Verification")
            if not _status_matches(vstat):
                continue
            if s_lower and s_lower not in t.title.lower() and not (t.description and s_lower in t.description.lower()):
                continue
            items.append({
                "id": t.id,
                "project_id": t.project_id,
                "category": "Tasks",
                "title": t.title,
                "subtitle": f"Owner: {t.owner} (Priority: {t.priority.upper()})",
                "content": t.description or "No description provided.",
                "summary": t.description or "No description provided.",
                "owner": t.owner,
                "date": t.deadline or (t.created_at.strftime("%Y-%m-%d") if t.created_at else ""),
                "status": t.status,
                "verification_status": vstat,
                "confidence": t.confidence,
                "is_departing": t.is_departing_owner,
                "suggested_reassignment": t.suggested_reassignment,
                "evidence_ids": t.evidence_ids or [],
                "tags": [t.priority, "Task"],
            })

    if not category or category.lower() in ["all", "responsibilities"]:
        for resp in db.query(Responsibility).filter(Responsibility.project_id.in_(p_ids)).all():
            conf = 0.85 if resp.evidence_ids else 0.5
            if min_confidence and conf < min_confidence:
                continue
            if emp_lower and emp_lower not in (resp.owner or "").lower():
                continue
            vstat = getattr(resp, "verification_status", "Needs Human Verification")
            if not _status_matches(vstat):
                continue
            if s_lower and s_lower not in resp.domain.lower() and s_lower not in resp.scope.lower():
                continue
            items.append({
                "id": resp.id,
                "project_id": resp.project_id,
                "category": "Responsibilities",
                "title": f"{resp.domain} ({resp.owner})",
                "subtitle": f"Owner: {resp.owner} | Criticality: {resp.criticality.upper()}",
                "content": resp.scope,
                "summary": resp.scope,
                "owner": resp.owner,
                "date": resp.created_at.strftime("%Y-%m-%d") if resp.created_at else "",
                "status": resp.criticality,
                "verification_status": vstat,
                "confidence": conf,
                "evidence_ids": resp.evidence_ids or [],
                "tags": ["Responsibility", resp.criticality],
            })

    if not category or category.lower() in ["all", "dependencies"]:
        for dep in db.query(Dependency).filter(Dependency.project_id.in_(p_ids)).all():
            conf = 0.9 if dep.evidence_ids else 0.6
            if min_confidence and conf < min_confidence:
                continue
            if emp_lower and emp_lower not in (dep.owner or "").lower():
                continue
            vstat = getattr(dep, "verification_status", "Needs Human Verification")
            if not _status_matches(vstat):
                continue
            if s_lower and s_lower not in dep.source_component.lower() and s_lower not in dep.target_component.lower():
                continue
            items.append({
                "id": dep.id,
                "project_id": dep.project_id,
                "category": "Dependencies",
                "title": f"{dep.source_component} → {dep.target_component}",
                "subtitle": f"Type: {dep.dependency_type.replace('_', ' ').capitalize()} | Criticality: {dep.criticality.upper()}",
                "content": dep.description or "Component dependency boundary.",
                "summary": dep.description or "Component dependency boundary.",
                "owner": dep.owner or "Unassigned",
                "date": dep.created_at.strftime("%Y-%m-%d") if dep.created_at else "",
                "confidence": conf,
                "status": dep.criticality,
                "verification_status": vstat,
                "evidence_ids": dep.evidence_ids or [],
                "tags": ["Dependency", dep.dependency_type],
            })

    if not category or category.lower() in ["all", "risks"]:
        for r in db.query(RiskItem).filter(RiskItem.project_id.in_(p_ids)).all():
            conf = 0.88 if r.evidence_ids else 0.55
            if min_confidence and conf < min_confidence:
                continue
            if emp_lower and emp_lower not in (getattr(r, "owner", None) or "").lower():
                continue
            vstat = getattr(r, "verification_status", "Needs Human Verification")
            if not _status_matches(vstat):
                continue
            if s_lower and s_lower not in r.title.lower() and s_lower not in r.description.lower():
                continue
            items.append({
                "id": r.id,
                "project_id": r.project_id,
                "category": "Risks",
                "title": r.title,
                "subtitle": f"Severity: {r.severity.upper()} | Likelihood: {r.likelihood.upper()}",
                "content": r.description,
                "summary": r.description,
                "mitigation": r.mitigation_strategy,
                "owner": getattr(r, "owner", None) or "Risk Owner",
                "date": r.created_at.strftime("%Y-%m-%d") if r.created_at else "",
                "status": r.status,
                "verification_status": vstat,
                "confidence": conf,
                "evidence_ids": r.evidence_ids or [],
                "tags": ["Risk", r.severity],
            })

    if not category or category.lower() in ["all", "gaps", "knowledge gaps", "questions"]:
        for g in db.query(KnowledgeGap).filter(KnowledgeGap.project_id.in_(p_ids)).all():
            gap_owner = getattr(g, "assigned_reviewer", None) or "Unassigned"
            gap_vstat = "Unknown / Missing Evidence"
            if min_confidence and 0.85 < min_confidence:
                continue
            if emp_lower and emp_lower not in gap_owner.lower():
                continue
            if not _status_matches(gap_vstat):
                continue
            if s_lower and s_lower not in g.title.lower() and s_lower not in g.description.lower():
                continue
            items.append({
                "id": g.id,
                "project_id": g.project_id,
                "category": "Knowledge Gaps",
                "title": g.title,
                "subtitle": f"Type: {g.gap_type.replace('_', ' ').capitalize()} | Severity: {g.severity.upper()}",
                "content": g.description,
                "summary": g.description,
                "impact": g.impact,
                "recommended_action": g.recommended_action,
                "owner": gap_owner,
                "date": g.created_at.strftime("%Y-%m-%d") if g.created_at else "",
                "status": g.status,
                "verification_status": gap_vstat,
                "confidence": 0.85,
                "tags": ["Gap", g.gap_type],
            })

    if not category or category.lower() in ["all", "entities", "technical"]:
        for e in db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id.in_(p_ids)).all():
            ent_owner = (e.properties or {}).get("owner", "System")
            ent_vstat = getattr(e, "verification_status", "Needs Human Verification")
            if min_confidence and (e.confidence or 0.0) < min_confidence:
                continue
            if emp_lower and emp_lower not in str(ent_owner).lower():
                continue
            if not _status_matches(ent_vstat):
                continue
            if s_lower and s_lower not in e.name.lower() and not (e.description and s_lower in e.description.lower()):
                continue
            items.append({
                "id": e.id,
                "project_id": e.project_id,
                "category": "Entities",
                "entity_type": e.entity_type,
                "title": e.name,
                "subtitle": f"Entity Type: {e.entity_type}",
                "content": e.description or "",
                "summary": e.description or "",
                "owner": ent_owner,
                "date": e.created_at.strftime("%Y-%m-%d") if e.created_at else "",
                "status": "active",
                "verification_status": ent_vstat,
                "confidence": e.confidence,
                "evidence_ids": [e.evidence_id] if e.evidence_id else [],
                "tags": [e.entity_type],
            })

    return items


@router.get("/entities")
def get_entities(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(KnowledgeEntity)
    if project_id:
        verify_project_access(project_id, current_user, db)
        query = query.filter(KnowledgeEntity.project_id == project_id)
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)
        if not p_ids:
            return []
        query = query.filter(KnowledgeEntity.project_id.in_(p_ids))
    return query.all()


@router.get("/relationships")
def get_relationships(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(KnowledgeRelationship)
    if project_id:
        verify_project_access(project_id, current_user, db)
        query = query.filter(KnowledgeRelationship.project_id == project_id)
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)
        if not p_ids:
            return []
        query = query.filter(KnowledgeRelationship.project_id.in_(p_ids))
    return query.all()


@router.get("/dependencies")
def get_dependencies(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    if project_id:
        verify_project_access(project_id, current_user, db)
        p_ids = [project_id]
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)

    if not p_ids:
        return []

    rows = db.query(Dependency).filter(Dependency.project_id.in_(p_ids)).all()
    results: List[Dict[str, Any]] = [
        {
            "id": d.id,
            "project_id": d.project_id,
            "source_component": d.source_component,
            "target_component": d.target_component,
            "dependency_type": d.dependency_type,
            "description": d.description or "",
            "owner": d.owner or "Unassigned",
            "criticality": d.criticality,
            "evidence_ids": d.evidence_ids or [],
            "created_at": d.created_at.isoformat() if d.created_at else "",
        }
        for d in rows
    ]

    if not results:
        ent_map = {
            e.id: e
            for e in db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id.in_(p_ids)).all()
        }
        for rel in db.query(KnowledgeRelationship).filter(KnowledgeRelationship.project_id.in_(p_ids)).all():
            src = ent_map.get(rel.source_entity_id)
            tgt = ent_map.get(rel.target_entity_id)
            if src and tgt:
                results.append({
                    "id": rel.id,
                    "project_id": rel.project_id,
                    "source_component": src.name,
                    "target_component": tgt.name,
                    "dependency_type": rel.relation_type,
                    "description": rel.context or "",
                    "owner": (src.properties or {}).get("owner", "System"),
                    "criticality": "high" if rel.relation_type in {"depends_on", "calls"} else "medium",
                    "evidence_ids": [rel.evidence_id] if rel.evidence_id else [],
                    "created_at": "",
                })
    return results


class DriftStatusUpdate(BaseModel):
    status: str  # acknowledged, resolved, dismissed


@router.get("/drift")
def list_knowledge_drift(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    if project_id:
        verify_project_access(project_id, current_user, db)
        p_ids = [project_id]
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)
    if not p_ids:
        return []

    query = db.query(KnowledgeDriftEvent).filter(KnowledgeDriftEvent.project_id.in_(p_ids))
    if status and status.lower() != "all":
        query = query.filter(KnowledgeDriftEvent.status == status.lower())
    rows = query.order_by(KnowledgeDriftEvent.created_at.desc()).limit(100).all()
    return [
        {
            "id": e.id,
            "project_id": e.project_id,
            "integration_id": e.integration_id,
            "source_record_id": e.source_record_id,
            "drift_type": e.drift_type,
            "severity": e.severity,
            "target_entity_type": e.target_entity_type,
            "target_entity_id": e.target_entity_id,
            "target_title": e.target_title,
            "summary": e.summary,
            "evidence_excerpt": e.evidence_excerpt,
            "status": e.status,
            "metadata_json": e.metadata_json or {},
            "created_at": e.created_at.isoformat() if e.created_at else "",
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
        }
        for e in rows
    ]


@router.post("/drift/scan")
def trigger_drift_scan(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    proj = get_effective_project(project_id, current_user, db, require_write=True)
    if not proj:
        raise HTTPException(status_code=404, detail="No accessible project found.")
    return scan_project_for_drift(db, proj.id, actor_user_id=current_user.id)


@router.patch("/drift/{drift_id}")
def update_drift_status(
    drift_id: str,
    req: DriftStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    ev = db.query(KnowledgeDriftEvent).filter(KnowledgeDriftEvent.id == drift_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Drift alert not found")
    verify_project_access(ev.project_id, current_user, db, require_write=True)
    allowed = {"open", "acknowledged", "resolved", "dismissed"}
    next_status = req.status.strip().lower()
    if next_status not in allowed:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(allowed)}")
    ev.status = next_status
    if next_status in ("resolved", "dismissed"):
        ev.resolved_by_user_id = current_user.id
        ev.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": ev.id, "status": ev.status, "resolved_at": ev.resolved_at.isoformat() if ev.resolved_at else None}
