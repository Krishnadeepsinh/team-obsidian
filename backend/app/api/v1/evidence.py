from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_user_accessible_project_ids, verify_project_access
from app.core.security import get_current_user
from app.models.evidence import Evidence, EvidenceReview
from app.models.workspace import User
from app.schemas.evidence import EvidenceAuditRequest, EvidenceResponse
from app.services.audit_service import record_activity

router = APIRouter(prefix="/evidence", tags=["Evidence Center"])


@router.get("", response_model=List[EvidenceResponse])
def list_evidence(
    project_id: Optional[str] = None,
    status: Optional[str] = Query(None),
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Evidence)
    if project_id:
        verify_project_access(project_id, current_user, db)
        query = query.filter(Evidence.project_id == project_id)
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)
        if not p_ids:
            return []
        query = query.filter(Evidence.project_id.in_(p_ids))

    if status and status.lower() != "all":
        query = query.filter(Evidence.verification_status == status)

    evidences = query.order_by(Evidence.created_at.desc()).all()
    if search:
        s = search.lower()
        evidences = [
            e
            for e in evidences
            if s in e.source_title.lower()
            or s in e.excerpt.lower()
            or s in e.ai_interpretation.lower()
            or (e.source_author and s in e.source_author.lower())
        ]
    return evidences


@router.get("/{evidence_id}", response_model=EvidenceResponse)
def get_evidence(
    evidence_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ev = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    verify_project_access(ev.project_id, current_user, db)
    return ev


@router.post("/{evidence_id}/audit", response_model=EvidenceResponse)
def audit_evidence(
    evidence_id: str,
    audit_in: EvidenceAuditRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Human-in-the-loop verification action to verify, reject, or flag conflicting evidence."""
    ev = db.query(Evidence).filter(Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")

    verify_project_access(ev.project_id, current_user, db, require_write=True)

    prev_status = ev.verification_status
    ev.verification_status = audit_in.new_status
    ev.reviewed_at = datetime.now(timezone.utc)
    ev.review_notes = audit_in.review_notes
    ev.reviewer_id = current_user.id

    review_record = EvidenceReview(
        evidence_id=ev.id,
        reviewer_id=current_user.id,
        reviewer_name=current_user.name,
        action=f"status_change_to_{audit_in.new_status.lower().replace(' ', '_')}",
        previous_status=prev_status,
        new_status=audit_in.new_status,
        notes=audit_in.review_notes,
    )
    db.add(review_record)
    record_activity(
        db=db,
        action="evidence.audited",
        entity_type="evidence",
        entity_id=ev.id,
        user_id=current_user.id,
        project_id=ev.project_id,
        actor_email=current_user.email,
        details={"message": f"Evidence '{ev.source_title}' status changed {prev_status} → {audit_in.new_status}"},
    )
    db.commit()
    db.refresh(ev)
    return ev
