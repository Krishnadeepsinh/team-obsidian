import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
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
from app.models.knowledge import KnowledgeDriftEvent, KnowledgeGap, TaskItem
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


@router.get("/{handover_id}/readiness-gate")
def get_handover_readiness_gate(
    handover_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Evaluate concrete pre-completion engineering sign-off gates for a handover dossier."""
    h = db.query(Handover).filter(Handover.id == handover_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Handover not found")
    verify_project_access(h.project_id, current_user, db)

    sections = db.query(HandoverSection).filter(HandoverSection.handover_id == handover_id).all()
    claims = (
        db.query(HandoverClaim)
        .join(HandoverSection, HandoverClaim.section_id == HandoverSection.id)
        .filter(HandoverSection.handover_id == handover_id)
        .all()
    )
    approvals = db.query(HandoverApproval).filter(HandoverApproval.handover_id == handover_id).all()
    open_crit_gaps = (
        db.query(KnowledgeGap)
        .filter(
            KnowledgeGap.project_id == h.project_id,
            KnowledgeGap.status == "open",
            KnowledgeGap.severity.in_(["critical", "high"]),
        )
        .count()
    )
    open_crit_drift = (
        db.query(KnowledgeDriftEvent)
        .filter(
            KnowledgeDriftEvent.project_id == h.project_id,
            KnowledgeDriftEvent.status == "open",
            KnowledgeDriftEvent.severity.in_(["critical", "high"]),
        )
        .count()
    )
    departing_open_tasks = (
        db.query(TaskItem)
        .filter(
            TaskItem.project_id == h.project_id,
            TaskItem.is_departing_owner == True,  # noqa: E712
            TaskItem.status != "completed",
        )
        .count()
    )

    total_sections = len(sections)
    verified_sections = sum(
        1 for s in sections if s.is_verified or (getattr(s, "verification_status", "") == "Verified by Reviewer")
    )
    unverified_claims = sum(
        1
        for c in claims
        if (getattr(c, "verification_status", "") or "").lower()
        in {"contradicted", "outdated", "unknown / missing evidence", "unverified", "disputed"}
    )
    pending_approvals = sum(
        1 for a in approvals if (a.status or "").lower() not in {"approved", "acknowledged"}
    )
    stats = h.reconstruction_stats or {}
    sim_passed = bool(stats.get("readiness_passed", False))
    sim_score = stats.get("latest_readiness_score")

    checks: List[Dict[str, Any]] = [
        {
            "key": "sections_verified",
            "label": "All handover sections verified",
            "passed": total_sections > 0 and verified_sections == total_sections,
            "current": f"{verified_sections}/{total_sections}",
            "blocking": True,
        },
        {
            "key": "claims_verified",
            "label": "No unverified or disputed claims",
            "passed": unverified_claims == 0,
            "current": f"{unverified_claims} unverified",
            "blocking": unverified_claims > 0,
        },
        {
            "key": "critical_gaps_resolved",
            "label": "High/critical knowledge gaps resolved",
            "passed": open_crit_gaps == 0,
            "current": f"{open_crit_gaps} open",
            "blocking": open_crit_gaps > 0,
        },
        {
            "key": "drift_resolved",
            "label": "High/critical knowledge drift reconciled",
            "passed": open_crit_drift == 0,
            "current": f"{open_crit_drift} open",
            "blocking": open_crit_drift > 0,
        },
        {
            "key": "departing_tasks_reassigned",
            "label": "Departing engineer tasks reassigned or closed",
            "passed": departing_open_tasks == 0,
            "current": f"{departing_open_tasks} remaining",
            "blocking": departing_open_tasks > 0,
        },
        {
            "key": "simulator_passed",
            "label": "Incoming engineer readiness simulator passed",
            "passed": sim_passed,
            "current": f"{sim_score}%" if sim_score is not None else "Not taken",
            "blocking": not sim_passed,
        },
        {
            "key": "approvals_complete",
            "label": "Required stakeholder approvals signed",
            "passed": len(approvals) > 0 and pending_approvals == 0,
            "current": f"{len(approvals) - pending_approvals}/{len(approvals)} signed",
            "blocking": pending_approvals > 0,
        },
    ]

    passed_count = sum(1 for c in checks if c["passed"])
    readiness_score = round((passed_count / len(checks)) * 100, 1)
    blockers = [f"{c['label']} ({c['current']})" for c in checks if not c["passed"]]

    return {
        "handover_id": h.id,
        "handover_status": h.status,
        "readiness_score": readiness_score,
        "passed_checks": passed_count,
        "total_checks": len(checks),
        "can_finalize": len(blockers) == 0,
        "blockers": blockers,
        "checks": checks,
    }


@router.get("/{handover_id}/export/markdown")
def export_handover_markdown(
    handover_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export the 16-section handover dossier as a portable repository-ready HANDOVER.md file."""
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

    lines: List[str] = [
        f"# {h.title}",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| **Project** | {p.name if p else 'Project'} |",
        f"| **Departing Engineer** | {h.departing_employee_name} ({h.departing_employee_role or 'Contributor'}) |",
        f"| **Incoming Successor** | {h.incoming_employee_name or 'Unassigned'} ({h.incoming_employee_role or 'Successor'}) |",
        f"| **Status** | `{h.status}` |",
        f"| **Overall Confidence** | {round((h.overall_confidence or 0) * 100, 1)}% |",
        f"| **Generated** | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} |",
        "",
        "## Sign-Off Approvals",
        "",
        "| Role | Approver | Status | Signed At |",
        "| --- | --- | --- | --- |",
    ]
    if approvals:
        for a in approvals:
            signed = a.signed_at.strftime("%Y-%m-%d") if a.signed_at else "Pending"
            lines.append(f"| {a.role} | {a.approver_name} | `{a.status}` | {signed} |")
    else:
        lines.append("| — | No approvers configured | — | — |")

    lines.append("")
    lines.append("---")
    lines.append("")

    for s in sections:
        v_status = getattr(s, "verification_status", "Needs Human Verification")
        badge = "VERIFIED" if s.is_verified or v_status == "Verified by Reviewer" else v_status
        lines.append(f"## {s.section_number}. {s.title}")
        lines.append(f"> Verification Status: **{badge}**")
        lines.append("")
        lines.append((s.content or "").strip() or "_No content recorded for this section._")
        lines.append("")
        refs = [ev_by_id[eid] for eid in (s.evidence_ids or []) if eid in ev_by_id]
        if refs:
            lines.append("**Verified Evidence Sources:**")
            for ev in refs[:8]:
                sha_short = (ev.content_hash or "")[:12]
                url_part = f" ([link]({ev.source_url}))" if ev.source_url else ""
                lines.append(f"- `{ev.source_type}` **{ev.source_title}** (SHA-256: `{sha_short}`){url_part}")
            lines.append("")

    md_content = "\n".join(lines)
    safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in h.departing_employee_name)
    filename = f"HANDOVER_{safe_name}_{h.id[:8]}.md"
    return Response(
        content=md_content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{handover_id}/simulator/create-onboarding-tasks")
def create_onboarding_tasks_from_simulator(
    handover_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Turn missed concepts from a readiness simulation into actionable onboarding tasks for the successor."""
    h = db.query(Handover).filter(Handover.id == handover_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Handover not found")
    verify_project_access(h.project_id, current_user, db, require_write=True)

    sim_id = (payload or {}).get("simulation_id")
    q = db.query(ReadinessSimulation).filter(ReadinessSimulation.handover_id == handover_id)
    if sim_id:
        sim = q.filter(ReadinessSimulation.id == sim_id).first()
    else:
        sim = q.order_by(ReadinessSimulation.created_at.desc()).first()

    if not sim:
        raise HTTPException(
            status_code=400,
            detail="No readiness simulation attempt found yet. Submit an evaluation first.",
        )

    existing_titles = {
        (t.title or "").strip().lower()
        for t in db.query(TaskItem).filter(TaskItem.project_id == h.project_id).all()
    }
    assignee = (h.incoming_employee_name or sim.candidate_name or current_user.name or current_user.email).strip()
    created_tasks: List[Dict[str, Any]] = []

    for resp_item in sim.responses_json or []:
        missed = [str(c).strip() for c in (resp_item.get("missed_concepts") or []) if str(c).strip()]
        score = float(resp_item.get("score") or 0)
        if not missed and score >= 75:
            continue

        scenario_title = str(resp_item.get("title") or resp_item.get("scenario_id") or "Readiness Topic").strip()
        task_title = f"Onboarding Study: {scenario_title}"[:240]
        if task_title.lower() in existing_titles:
            continue

        missed_str = ", ".join(missed) if missed else "Review architectural decision & failover sequence"
        t = TaskItem(
            project_id=h.project_id,
            created_by_user_id=current_user.id,
            title=task_title,
            description=(
                f"Auto-generated from Readiness Simulator (score: {round(score)}%).\n"
                f"Missed key concepts to master with mentor/docs: {missed_str}\n"
                f"Coach feedback: {resp_item.get('feedback') or ''}"
            ).strip(),
            owner=assignee,
            priority="high" if score < 60 else "medium",
            status="open",
            is_departing_owner=False,
        )
        db.add(t)
        db.flush()
        existing_titles.add(task_title.lower())
        created_tasks.append({"id": t.id, "title": t.title, "owner": t.owner, "priority": t.priority})

    if created_tasks:
        record_activity(
            db=db,
            action="simulator.onboarding_tasks_created",
            entity_type="handover",
            entity_id=h.id,
            user_id=current_user.id,
            project_id=h.project_id,
            actor_email=current_user.email,
            details={"message": f"Created {len(created_tasks)} onboarding task(s) from readiness simulator gaps"},
        )
        db.commit()

    return {
        "created_count": len(created_tasks),
        "assignee": assignee,
        "tasks": created_tasks,
    }

