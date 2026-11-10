from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_effective_project, get_user_accessible_project_ids, verify_project_access
from app.core.security import get_current_user
from app.models.knowledge import RiskItem
from app.models.workspace import User
from app.schemas.knowledge import RiskCreate, RiskResponse
from app.services.audit_service import record_activity

router = APIRouter(prefix="/risks", tags=["Risks & Issues"])


@router.get("", response_model=List[RiskResponse])
def list_risks(
    project_id: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(RiskItem)
    if project_id:
        verify_project_access(project_id, current_user, db)
        query = query.filter(RiskItem.project_id == project_id)
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)
        if not p_ids:
            return []
        query = query.filter(RiskItem.project_id.in_(p_ids))

    if severity:
        query = query.filter(RiskItem.severity == severity)
    if status:
        query = query.filter(RiskItem.status == status)
    return query.order_by(RiskItem.created_at.desc()).all()


@router.post("", response_model=RiskResponse)
def create_risk(
    risk_in: RiskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    eff_proj = get_effective_project(risk_in.project_id, current_user, db, require_write=True)
    if not eff_proj:
        raise HTTPException(status_code=400, detail="No accessible project found. Please create a project first.")

    r = RiskItem(
        project_id=eff_proj.id,
        created_by_user_id=current_user.id,
        title=risk_in.title,
        description=risk_in.description,
        category=risk_in.category or "technical_risk",
        severity=risk_in.severity or "high",
        likelihood=risk_in.likelihood or "medium",
        mitigation_strategy=risk_in.mitigation_strategy,
        owner=current_user.name,
        related_components=risk_in.related_components or [],
        evidence_ids=risk_in.evidence_ids or [],
        verification_status="Supported by Evidence" if risk_in.evidence_ids else "Needs Human Verification",
    )
    db.add(r)
    db.flush()
    record_activity(
        db=db,
        action="risk.created",
        entity_type="risk",
        entity_id=r.id,
        user_id=current_user.id,
        project_id=eff_proj.id,
        actor_email=current_user.email,
        details={"message": f"Logged risk '{r.title}' ({r.severity})"},
    )
    db.commit()
    db.refresh(r)
    return r


@router.put("/{risk_id}/status", response_model=RiskResponse)
def update_risk_status(
    risk_id: str,
    status: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    r = db.query(RiskItem).filter(RiskItem.id == risk_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Risk not found")
    verify_project_access(r.project_id, current_user, db, require_write=True)
    r.status = status
    db.commit()
    db.refresh(r)
    return r
