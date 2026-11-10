from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_effective_project, get_user_accessible_project_ids, verify_project_access
from app.core.security import get_current_user
from app.models.knowledge import Decision
from app.models.workspace import User
from app.schemas.knowledge import DecisionCreate, DecisionResponse
from app.services.audit_service import record_activity

router = APIRouter(prefix="/decisions", tags=["Decisions"])


@router.get("", response_model=List[DecisionResponse])
def list_decisions(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Decision)
    if project_id:
        verify_project_access(project_id, current_user, db)
        query = query.filter(Decision.project_id == project_id)
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)
        if not p_ids:
            return []
        query = query.filter(Decision.project_id.in_(p_ids))

    if status:
        query = query.filter(Decision.status == status)
    return query.order_by(Decision.date.desc()).all()


@router.post("", response_model=DecisionResponse)
def create_decision(
    decision_in: DecisionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    eff_proj = get_effective_project(decision_in.project_id, current_user, db, require_write=True)
    if not eff_proj:
        raise HTTPException(status_code=400, detail="No accessible project found. Please create a project first.")

    d = Decision(
        project_id=eff_proj.id,
        created_by_user_id=current_user.id,
        title=decision_in.title,
        summary=decision_in.summary,
        reasoning=decision_in.reasoning,
        decision_maker=decision_in.decision_maker or current_user.name,
        date=decision_in.date,
        component=decision_in.component,
        decision_type=decision_in.decision_type or "technical",
        status=decision_in.status or "accepted",
        verification_status="Verified by Reviewer" if not decision_in.evidence_ids else "Supported by Evidence",
        alternatives=decision_in.alternatives or [],
        tradeoffs=decision_in.tradeoffs or [],
        risks=decision_in.risks or [],
        supersedes=decision_in.supersedes or [],
        evidence_ids=decision_in.evidence_ids or [],
        confidence=1.0 if decision_in.evidence_ids else 0.5,
    )
    db.add(d)
    db.flush()
    record_activity(
        db=db,
        action="decision.created",
        entity_type="decision",
        entity_id=d.id,
        user_id=current_user.id,
        project_id=eff_proj.id,
        actor_email=current_user.email,
        details={"message": f"Recorded decision '{d.title}'"},
    )
    db.commit()
    db.refresh(d)
    return d


@router.get("/{decision_id}", response_model=DecisionResponse)
def get_decision(
    decision_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    d = db.query(Decision).filter(Decision.id == decision_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Decision not found")
    verify_project_access(d.project_id, current_user, db)
    return d
