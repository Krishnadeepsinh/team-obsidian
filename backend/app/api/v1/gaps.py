from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_effective_project, get_user_accessible_project_ids, verify_project_access
from app.core.security import get_current_user
from app.models.knowledge import KnowledgeGap
from app.models.workspace import User
from app.schemas.knowledge import GapCreate, GapResponse
from app.services.audit_service import record_activity

router = APIRouter(prefix="/gaps", tags=["Knowledge Gaps"])


@router.get("", response_model=List[GapResponse])
def list_gaps(
    project_id: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(KnowledgeGap)
    if project_id:
        verify_project_access(project_id, current_user, db)
        query = query.filter(KnowledgeGap.project_id == project_id)
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)
        if not p_ids:
            return []
        query = query.filter(KnowledgeGap.project_id.in_(p_ids))

    if severity:
        query = query.filter(KnowledgeGap.severity == severity)
    if status:
        query = query.filter(KnowledgeGap.status == status)
    return query.order_by(KnowledgeGap.created_at.desc()).all()


@router.post("", response_model=GapResponse)
def create_gap(
    gap_in: GapCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    eff_proj = get_effective_project(gap_in.project_id, current_user, db, require_write=True)
    if not eff_proj:
        raise HTTPException(status_code=400, detail="No accessible project found. Please create a project first.")

    g = KnowledgeGap(
        project_id=eff_proj.id,
        title=gap_in.title,
        description=gap_in.description,
        gap_type=gap_in.gap_type,
        severity=gap_in.severity or "high",
        priority=gap_in.severity or "high",
        impact=gap_in.impact,
        business_impact=gap_in.impact,
        technical_impact=gap_in.impact,
        recommended_action=gap_in.recommended_action,
        assigned_reviewer=current_user.name,
    )
    db.add(g)
    db.flush()
    record_activity(
        db=db,
        action="gap.created",
        entity_type="knowledge_gap",
        entity_id=g.id,
        user_id=current_user.id,
        project_id=eff_proj.id,
        actor_email=current_user.email,
        details={"message": f"Identified knowledge gap '{g.title}'"},
    )
    db.commit()
    db.refresh(g)
    return g


@router.put("/{gap_id}/resolve", response_model=GapResponse)
def resolve_gap(
    gap_id: str,
    status: str = Body("resolved", embed=True),
    resolution_notes: Optional[str] = Body(None, embed=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    g = db.query(KnowledgeGap).filter(KnowledgeGap.id == gap_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Knowledge gap not found")
    verify_project_access(g.project_id, current_user, db, require_write=True)
    g.status = status
    if resolution_notes:
        g.recommended_action = f"{g.recommended_action} | Resolution: {resolution_notes}"
    record_activity(
        db=db,
        action="gap.updated",
        entity_type="knowledge_gap",
        entity_id=g.id,
        user_id=current_user.id,
        project_id=g.project_id,
        actor_email=current_user.email,
        details={"message": f"Updated knowledge gap '{g.title}' to status '{status}'"},
    )
    db.commit()
    db.refresh(g)
    return g
