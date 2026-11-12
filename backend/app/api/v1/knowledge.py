from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
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
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
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
    s_pat = f"%{s_lower}%" if s_lower else None
    emp_lower = employee.strip().lower() if employee and employee.strip() else None
    emp_pat = f"%{emp_lower}%" if emp_lower else None
    vs_lower = verification_status.strip().lower() if verification_status and verification_status.strip().lower() != "all" else None
    per_table_cap = offset + limit

    def _status_matches(raw_vstat: Optional[str]) -> bool:
        if not vs_lower:
            return True
        actual = (raw_vstat or "").strip().lower()
        if vs_lower in ("verified", "verified by reviewer"):
            return actual in ("verified", "verified by reviewer")
        return actual == vs_lower

    def _apply_sql_status_filter(q, col):
        if not vs_lower:
            return q
        if vs_lower in ("verified", "verified by reviewer"):
            return q.filter(func.lower(col).in_(["verified", "verified by reviewer"]))
        return q.filter(func.lower(col) == vs_lower)

    if not category or category.lower() in ["all", "decisions"]:
        dq = db.query(Decision).filter(Decision.project_id.in_(p_ids))
        if min_confidence:
            dq = dq.filter(Decision.confidence >= min_confidence)
        if emp_pat:
            dq = dq.filter(Decision.decision_maker.ilike(emp_pat))
        dq = _apply_sql_status_filter(dq, Decision.verification_status)
        if s_pat:
            dq = dq.filter(or_(Decision.title.ilike(s_pat), Decision.summary.ilike(s_pat), Decision.reasoning.ilike(s_pat)))
        for d in dq.order_by(Decision.created_at.desc()).limit(per_table_cap).all():
            vstat = getattr(d, "verification_status", "Needs Human Verification")
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
        tq = db.query(TaskItem).filter(TaskItem.project_id.in_(p_ids))
        if min_confidence:
            tq = tq.filter(TaskItem.confidence >= min_confidence)
        if emp_pat:
            tq = tq.filter(TaskItem.owner.ilike(emp_pat))
        tq = _apply_sql_status_filter(tq, TaskItem.verification_status)
        if s_pat:
            tq = tq.filter(or_(TaskItem.title.ilike(s_pat), TaskItem.description.ilike(s_pat)))
        for t in tq.order_by(TaskItem.created_at.desc()).limit(per_table_cap).all():
            vstat = getattr(t, "verification_status", "Needs Human Verification")
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
        rq = db.query(Responsibility).filter(Responsibility.project_id.in_(p_ids))
        if emp_pat:
            rq = rq.filter(Responsibility.owner.ilike(emp_pat))
        rq = _apply_sql_status_filter(rq, Responsibility.verification_status)
        if s_pat:
            rq = rq.filter(or_(Responsibility.domain.ilike(s_pat), Responsibility.scope.ilike(s_pat)))
        for resp in rq.order_by(Responsibility.created_at.desc()).limit(per_table_cap).all():
            conf = 0.85 if resp.evidence_ids else 0.5
            if min_confidence and conf < min_confidence:
                continue
            vstat = getattr(resp, "verification_status", "Needs Human Verification")
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
        dpq = db.query(Dependency).filter(Dependency.project_id.in_(p_ids))
        if emp_pat:
            dpq = dpq.filter(Dependency.owner.ilike(emp_pat))
        dpq = _apply_sql_status_filter(dpq, Dependency.verification_status)
        if s_pat:
            dpq = dpq.filter(or_(Dependency.source_component.ilike(s_pat), Dependency.target_component.ilike(s_pat)))
        for dep in dpq.order_by(Dependency.created_at.desc()).limit(per_table_cap).all():
            conf = 0.9 if dep.evidence_ids else 0.6
            if min_confidence and conf < min_confidence:
                continue
            vstat = getattr(dep, "verification_status", "Needs Human Verification")
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
        rkq = db.query(RiskItem).filter(RiskItem.project_id.in_(p_ids))
        if emp_pat:
            rkq = rkq.filter(RiskItem.owner.ilike(emp_pat))
        rkq = _apply_sql_status_filter(rkq, RiskItem.verification_status)
        if s_pat:
            rkq = rkq.filter(or_(RiskItem.title.ilike(s_pat), RiskItem.description.ilike(s_pat)))
        for r in rkq.order_by(RiskItem.created_at.desc()).limit(per_table_cap).all():
            conf = 0.88 if r.evidence_ids else 0.55
            if min_confidence and conf < min_confidence:
                continue
            vstat = getattr(r, "verification_status", "Needs Human Verification")
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
        gq = db.query(KnowledgeGap).filter(KnowledgeGap.project_id.in_(p_ids))
        if emp_pat:
            gq = gq.filter(KnowledgeGap.assigned_reviewer.ilike(emp_pat))
        if s_pat:
            gq = gq.filter(or_(KnowledgeGap.title.ilike(s_pat), KnowledgeGap.description.ilike(s_pat)))
        if (not min_confidence or 0.85 >= min_confidence) and _status_matches("Unknown / Missing Evidence"):
            for g in gq.order_by(KnowledgeGap.created_at.desc()).limit(per_table_cap).all():
                gap_owner = getattr(g, "assigned_reviewer", None) or "Unassigned"
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
                    "verification_status": "Unknown / Missing Evidence",
                    "confidence": 0.85,
                    "tags": ["Gap", g.gap_type],
                })

    if not category or category.lower() in ["all", "entities", "technical"]:
        eq = db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id.in_(p_ids))
        if min_confidence:
            eq = eq.filter(KnowledgeEntity.confidence >= min_confidence)
        eq = _apply_sql_status_filter(eq, KnowledgeEntity.verification_status)
        if s_pat:
            eq = eq.filter(or_(KnowledgeEntity.name.ilike(s_pat), KnowledgeEntity.description.ilike(s_pat)))
        for e in eq.order_by(KnowledgeEntity.created_at.desc()).limit(per_table_cap).all():
            ent_owner = (e.properties or {}).get("owner", "System")
            ent_vstat = getattr(e, "verification_status", "Needs Human Verification")
            if emp_lower and emp_lower not in str(ent_owner).lower():
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

    return items[offset : offset + limit]


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
