import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    APPROVER_ROLES,
    get_effective_project,
    get_user_accessible_project_ids,
    get_user_project_role,
    normalize_role,
    verify_project_access,
)
from app.core.security import get_current_user
from app.models.evidence import Evidence
from app.models.handover import (
    HANDOVER_STATES,
    Handover,
    HandoverApproval,
    HandoverClaim,
    HandoverSection,
    HandoverVersion,
    ReadinessSimulation,
)
from app.models.workspace import Project, ProjectMember, User
from app.services.email_service import email_service
from app.services.readiness_simulator import evaluate_simulation_submission, generate_scenarios_for_handover
from app.schemas.handover import (
    ClaimVerifyRequest,
    HandoverApprovalRequest,
    HandoverClaimResponse,
    HandoverReconstructRequest,
    HandoverResponse,
    HandoverSectionResponse,
    HandoverStatusRequest,
    SectionCommentRequest,
    SectionEditRequest,
    SectionReviewRequest,
    SimulatorEvaluateRequest,
)
from app.services.audit_service import record_activity
from app.services.handover_engine import handover_engine
from app.services.pdf_generator import pdf_generator

router = APIRouter(prefix="/handovers", tags=["Handover Engine"])


@router.get("", response_model=List[HandoverResponse])
def list_handovers(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Handover)
    if project_id:
        verify_project_access(project_id, current_user, db)
        query = query.filter(Handover.project_id == project_id)
    else:
        accessible_ids = get_user_accessible_project_ids(current_user, db)
        if not accessible_ids:
            return []
        query = query.filter(Handover.project_id.in_(accessible_ids))
    return query.order_by(Handover.created_at.desc()).all()


@router.get("/{handover_id}", response_model=HandoverResponse)
def get_handover(
    handover_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    h = db.query(Handover).filter(Handover.id == handover_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Handover dossier not found")
    verify_project_access(h.project_id, current_user, db)
    return h


@router.post("/reconstruct", response_model=HandoverResponse)
def run_reconstruction(
    req: HandoverReconstructRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_effective_project(req.project_id, current_user, db, require_write=True)
    if not project:
        raise HTTPException(status_code=404, detail="No accessible project found for this user.")

    sources = req.selected_source_ids or req.selected_sources or []
    approvers_cfg = [a.model_dump() for a in req.approvers] if req.approvers else None

    h = handover_engine.reconstruct_and_generate(
        db=db,
        project_id=project.id,
        departing_name=req.departing_employee_name.strip(),
        departing_role=req.departing_employee_role.strip(),
        incoming_name=req.incoming_employee_name.strip(),
        incoming_role=req.incoming_employee_role.strip(),
        source_ids=sources,
        categories=req.selected_categories or ["Architecture", "Decisions", "Tasks", "Risks", "Gaps"],
        target_date=req.target_date,
        approvers=approvers_cfg,
        created_by_user_id=current_user.id,
    )
    _notify_stakeholders_of_handover(db, h, role_label="Stakeholder / Reviewer")
    return h


@router.put("/{handover_id}/sections/{section_id}", response_model=HandoverSectionResponse)
def edit_section(
    handover_id: str,
    section_id: str,
    edit_in: SectionEditRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    h = db.query(Handover).filter(Handover.id == handover_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Handover not found")
    verify_project_access(h.project_id, current_user, db, require_write=True)

    sec = (
        db.query(HandoverSection)
        .filter(HandoverSection.id == section_id, HandoverSection.handover_id == handover_id)
        .first()
    )
    if not sec:
        raise HTTPException(status_code=404, detail="Handover section not found")

    prev_content = sec.content
    sec.content = edit_in.content
    if edit_in.is_verified is not None:
        sec.is_verified = edit_in.is_verified
        sec.verification_status = (
            edit_in.verification_status
            or ("Verified by Reviewer" if edit_in.is_verified else "Needs Human Verification")
        )
    elif edit_in.verification_status:
        sec.verification_status = edit_in.verification_status
        sec.is_verified = edit_in.verification_status == "Verified by Reviewer"

    sec.updated_at = datetime.now(timezone.utc)

    v_count = db.query(HandoverVersion).filter(HandoverVersion.handover_id == handover_id).count()
    db.add(
        HandoverVersion(
            handover_id=handover_id,
            version_number=v_count + 1,
            user_id=current_user.id,
            changed_section=f"Section {sec.section_number}: {sec.title}",
            previous_content=prev_content,
            new_content=edit_in.content,
            reason=edit_in.reason or "Reviewer edit",
            changelog=f"Updated Section {sec.section_number}: {sec.title}",
            snapshot={"section_number": sec.section_number, "content_len": len(sec.content)},
            created_by=current_user.name or current_user.email,
        )
    )
    record_activity(
        db=db,
        action="handover.section_edited",
        entity_type="handover_section",
        entity_id=sec.id,
        user_id=current_user.id,
        project_id=h.project_id,
        actor_email=current_user.email,
        details={"message": f"Edited Section {sec.section_number} ({sec.title})"},
    )
    db.commit()
    db.refresh(sec)
    return sec


@router.post("/{handover_id}/sections/{section_id}/review", response_model=HandoverSectionResponse)
def review_section(
    handover_id: str,
    section_id: str,
    rev_in: SectionReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    h = db.query(Handover).filter(Handover.id == handover_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Handover not found")
    proj = verify_project_access(h.project_id, current_user, db, require_write=True)
    eff_role = get_user_project_role(proj, current_user, db)
    if eff_role not in APPROVER_ROLES:
        raise HTTPException(status_code=403, detail="Reviewer or lead role required to review sections.")

    sec = (
        db.query(HandoverSection)
        .filter(HandoverSection.id == section_id, HandoverSection.handover_id == handover_id)
        .first()
    )
    if not sec:
        raise HTTPException(status_code=404, detail="Handover section not found")

    action = rev_in.action.lower()
    if action in ("verify", "approve"):
        sec.is_verified = True
        sec.verification_status = rev_in.verification_status or "Verified by Reviewer"
    elif action in ("reject", "request_changes"):
        sec.is_verified = False
        sec.verification_status = rev_in.verification_status or "Contradicted" if action == "reject" else "Needs Human Verification"
        if action == "request_changes":
            h.status = "changes_requested"
    else:
        raise HTTPException(status_code=400, detail="Invalid review action. Use verify, approve, reject, or request_changes.")

    if rev_in.notes:
        comments = list(sec.comments or [])
        comments.append({
            "id": str(len(comments) + 1),
            "author": current_user.name,
            "text": f"[{action.upper()}] {rev_in.notes}",
            "date": datetime.now(timezone.utc).isoformat(),
        })
        sec.comments = comments

    record_activity(
        db=db,
        action=f"handover.section_{action}",
        entity_type="handover_section",
        entity_id=sec.id,
        user_id=current_user.id,
        project_id=h.project_id,
        actor_email=current_user.email,
        details={"message": f"Section {sec.section_number} marked {sec.verification_status}"},
    )
    db.commit()
    db.refresh(sec)
    return sec


@router.post("/{handover_id}/claims/{claim_id}/verify", response_model=HandoverClaimResponse)
def verify_claim(
    handover_id: str,
    claim_id: str,
    req: ClaimVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    h = db.query(Handover).filter(Handover.id == handover_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Handover not found")
    verify_project_access(h.project_id, current_user, db, require_write=True)

    claim = (
        db.query(HandoverClaim)
        .filter(HandoverClaim.id == claim_id, HandoverClaim.handover_id == handover_id)
        .first()
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Handover claim not found")

    claim.verification_status = req.verification_status
    claim.review_notes = req.review_notes
    claim.reviewer_id = current_user.id
    claim.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(claim)
    return claim


@router.post("/{handover_id}/sections/{section_id}/comments", response_model=HandoverSectionResponse)
def add_section_comment(
    handover_id: str,
    section_id: str,
    comment_in: SectionCommentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    h = db.query(Handover).filter(Handover.id == handover_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Handover not found")
    verify_project_access(h.project_id, current_user, db)

    sec = (
        db.query(HandoverSection)
        .filter(HandoverSection.id == section_id, HandoverSection.handover_id == handover_id)
        .first()
    )
    if not sec:
        raise HTTPException(status_code=404, detail="Handover section not found")

    comments = list(sec.comments or [])
    comments.append({
        "id": str(len(comments) + 1),
        "author": current_user.name or comment_in.author or current_user.email,
        "text": comment_in.text,
        "date": datetime.now(timezone.utc).isoformat(),
    })
    sec.comments = comments
    db.commit()
    db.refresh(sec)
    return sec


@router.post("/{handover_id}/approve", response_model=HandoverResponse)
def sign_off_approval(
    handover_id: str,
    app_in: HandoverApprovalRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    h = db.query(Handover).filter(Handover.id == handover_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Handover not found")
    proj = verify_project_access(h.project_id, current_user, db, require_write=True)
    eff_role = get_user_project_role(proj, current_user, db)
    if eff_role not in APPROVER_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden: Only authorized stakeholders can sign off.")

    norm_role = normalize_role(app_in.role)
    app_record = (
        db.query(HandoverApproval)
        .filter(HandoverApproval.handover_id == handover_id, HandoverApproval.role == norm_role)
        .first()
    )
    approver = app_in.approver_name or current_user.name or current_user.email
    if not app_record:
        app_record = HandoverApproval(
            handover_id=handover_id,
            approver_user_id=current_user.id,
            approver_name=approver,
            role=norm_role,
        )
        db.add(app_record)

    app_record.status = app_in.status
    app_record.notes = app_in.notes
    app_record.approver_name = approver
    app_record.approver_user_id = current_user.id
    app_record.signed_at = datetime.now(timezone.utc)
    db.flush()

    all_apps = db.query(HandoverApproval).filter(HandoverApproval.handover_id == handover_id).all()
    required_apps = [a for a in all_apps if getattr(a, "is_required", True)]
    if not required_apps:
        required_apps = all_apps

    if app_in.status == "rejected" or any(a.status == "rejected" for a in all_apps):
        h.status = "rejected"
    elif app_in.status == "changes_requested" or any(a.status == "changes_requested" for a in all_apps):
        h.status = "changes_requested"
    elif all(a.status in ("approved", "acknowledged") for a in required_apps) and required_apps:
        inc_ack = any(a.role == "incoming_employee" and a.status == "acknowledged" for a in all_apps)
        h.status = "acknowledged" if inc_ack else "approved"
    else:
        h.status = "in_review"

    v_count = db.query(HandoverVersion).filter(HandoverVersion.handover_id == handover_id).count()
    db.add(
        HandoverVersion(
            handover_id=handover_id,
            version_number=v_count + 1,
            user_id=current_user.id,
            changed_section="Approvals",
            changelog=f"{norm_role} ({approver}) marked {app_in.status}",
            reason=app_in.notes or f"Stakeholder {app_in.status}",
            snapshot={"status": h.status, "role": norm_role},
            created_by=approver,
        )
    )
    record_activity(
        db=db,
        action=f"handover.{app_in.status}",
        entity_type="handover",
        entity_id=h.id,
        user_id=current_user.id,
        project_id=h.project_id,
        actor_email=current_user.email,
        details={"message": f"Handover '{h.title}' sign-off '{app_in.status}' by {approver} ({norm_role})"},
    )
    db.commit()
    db.refresh(h)
    return h


def _notify_stakeholders_of_handover(db: Session, h: Handover, role_label: str = "Reviewer") -> None:
    try:
        proj = db.query(Project).filter(Project.id == h.project_id).first()
        pname = proj.name if proj else "Project"
        members = db.query(ProjectMember).filter(ProjectMember.project_id == h.project_id).all()
        user_ids = [m.user_id for m in members]
        if proj and proj.creator_id and proj.creator_id not in user_ids:
            user_ids.append(proj.creator_id)
        for u in db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []:
            email_service.send_handover_review_email(
                to_email=u.email,
                reviewer_name=u.name or u.email,
                handover_title=h.title,
                project_name=pname,
                role=role_label,
            )
    except Exception:
        pass


@router.get("/{handover_id}/simulator")
def get_readiness_simulator(
    handover_id: str,
    regenerate: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return project-grounded incident/ADR readiness scenarios and evaluation history for this handover."""
    h = db.query(Handover).filter(Handover.id == handover_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Handover not found")
    verify_project_access(h.project_id, current_user, db)

    history = (
        db.query(ReadinessSimulation)
        .filter(ReadinessSimulation.handover_id == handover_id)
        .order_by(ReadinessSimulation.created_at.desc())
        .limit(10)
        .all()
    )
    stats = dict(h.reconstruction_stats or {})
    if history and not regenerate and history[0].scenarios_json:
        scenarios = history[0].scenarios_json
    elif not regenerate and stats.get("active_simulator_scenarios"):
        scenarios = stats["active_simulator_scenarios"]
    else:
        scenarios = generate_scenarios_for_handover(db, h)
        stats["active_simulator_scenarios"] = scenarios
        h.reconstruction_stats = stats
        db.commit()

    return {
        "handover_id": h.id,
        "handover_title": h.title,
        "incoming_employee_name": h.incoming_employee_name,
        "departing_employee_name": h.departing_employee_name,
        "scenarios": scenarios,
        "latest_score": (h.reconstruction_stats or {}).get("latest_readiness_score"),
        "readiness_passed": (h.reconstruction_stats or {}).get("readiness_passed", False),
        "history": [
            {
                "id": sim.id,
                "candidate_name": sim.candidate_name,
                "overall_score": sim.overall_score,
                "passed": sim.passed,
                "responses": sim.responses_json or [],
                "summary_feedback": sim.summary_feedback,
                "created_at": sim.created_at.isoformat() if sim.created_at else "",
            }
            for sim in history
        ],
    }


@router.post("/{handover_id}/simulator/evaluate")
def evaluate_readiness_simulator(
    handover_id: str,
    payload: SimulatorEvaluateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Grade incoming engineer answers across server-issued SPOF/ADR/dependency readiness scenarios."""
    h = db.query(Handover).filter(Handover.id == handover_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Handover not found")
    verify_project_access(h.project_id, current_user, db, require_write=True)

    stats = dict(h.reconstruction_stats or {})
    scenarios = stats.get("active_simulator_scenarios")
    if not scenarios:
        last_sim = (
            db.query(ReadinessSimulation)
            .filter(ReadinessSimulation.handover_id == handover_id)
            .order_by(ReadinessSimulation.created_at.desc())
            .first()
        )
        scenarios = (last_sim.scenarios_json if last_sim and last_sim.scenarios_json else None) or generate_scenarios_for_handover(db, h)
        stats["active_simulator_scenarios"] = scenarios
        h.reconstruction_stats = stats
        db.flush()

    answers = payload.answers or {}
    candidate_name = (payload.candidate_name or h.incoming_employee_name or current_user.name or current_user.email).strip()

    sim = evaluate_simulation_submission(
        db=db,
        handover=h,
        candidate_name=candidate_name,
        user_id=current_user.id,
        scenarios=scenarios,
        answers=answers,
    )
    return {
        "id": sim.id,
        "handover_id": sim.handover_id,
        "candidate_name": sim.candidate_name,
        "overall_score": sim.overall_score,
        "passed": sim.passed,
        "responses": sim.responses_json or [],
        "summary_feedback": sim.summary_feedback,
        "created_at": sim.created_at.isoformat() if sim.created_at else "",
    }


@router.post("/{handover_id}/status", response_model=HandoverResponse)
def update_handover_status(
    handover_id: str,
    req: HandoverStatusRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    h = db.query(Handover).filter(Handover.id == handover_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Handover not found")
    verify_project_access(h.project_id, current_user, db, require_admin=True)
    if req.status not in HANDOVER_STATES:
        raise HTTPException(status_code=400, detail=f"Invalid handover state '{req.status}'.")
    prev = h.status
    h.status = req.status
    v_count = db.query(HandoverVersion).filter(HandoverVersion.handover_id == handover_id).count()
    db.add(
        HandoverVersion(
            handover_id=handover_id,
            version_number=v_count + 1,
            user_id=current_user.id,
            changed_section="Lifecycle Status",
            previous_content=prev,
            new_content=req.status,
            reason=req.reason or "Status transition",
            changelog=f"Transitioned handover status {prev} → {req.status}",
            snapshot={"status": req.status},
            created_by=current_user.name or current_user.email,
        )
    )
    db.commit()
    db.refresh(h)
    return h


@router.get("/{handover_id}/pdf")
def export_handover_pdf(
    handover_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    h = db.query(Handover).filter(Handover.id == handover_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Handover not found")
    verify_project_access(h.project_id, current_user, db)

    p = db.query(Project).filter(Project.id == h.project_id).first()
    sections = (
        db.query(HandoverSection)
        .filter(HandoverSection.handover_id == handover_id)
        .order_by(HandoverSection.section_number.asc())
        .all()
    )
    approvals = db.query(HandoverApproval).filter(HandoverApproval.handover_id == handover_id).all()
    evidences = db.query(Evidence).filter(Evidence.project_id == h.project_id).all()
    ev_by_id = {e.id: e for e in evidences}

    handover_data = {
        "title": h.title,
        "project_name": p.name if p else "Project",
        "departing_employee_name": h.departing_employee_name,
        "departing_employee_role": h.departing_employee_role,
        "incoming_employee_name": h.incoming_employee_name,
        "incoming_employee_role": h.incoming_employee_role,
        "overall_confidence": h.overall_confidence,
        "status": h.status,
        "created_at": h.created_at.strftime("%B %d, %Y"),
        "approvals": [
            {
                "role": a.role,
                "approver_name": a.approver_name,
                "status": a.status,
                "signed_at": a.signed_at.strftime("%Y-%m-%d") if a.signed_at else "Pending",
            }
            for a in approvals
        ],
        "sections": [
            {
                "section_number": s.section_number,
                "title": s.title,
                "content": s.content,
                "is_verified": s.is_verified,
                "verification_status": getattr(s, "verification_status", "Needs Human Verification"),
                "evidence_refs": [
                    f"{ev_by_id[eid].source_title} ({ev_by_id[eid].content_hash[:12]})"
                    for eid in (s.evidence_ids or [])
                    if eid in ev_by_id
                ][:5],
            }
            for s in sections
        ],
    }

    out_dir = os.path.join(os.getcwd(), "generated_reports")
    os.makedirs(out_dir, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in h.departing_employee_name)
    pdf_filename = f"Handover_{safe_name}_{h.id[:8]}.pdf"
    output_path = os.path.join(out_dir, pdf_filename)

    pdf_generator.generate_handover_pdf(handover_data, output_path)
    return FileResponse(output_path, media_type="application/pdf", filename=pdf_filename)
