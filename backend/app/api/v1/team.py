from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import get_user_accessible_project_ids, normalize_role
from app.core.security import get_current_user
from app.models.workspace import ActivityLog, Notification, Organization, ProjectMember, User
from app.schemas.auth import UserResponse
from app.services.ai_engine import ai_engine
from app.services.audit_service import record_activity

router = APIRouter(prefix="/team", tags=["Organisation"])


@router.get("/members", response_model=List[UserResponse])
def list_team_members(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List only users who share an organization or accessible project with the authenticated user."""
    accessible_project_ids = get_user_accessible_project_ids(current_user, db)
    member_user_ids = {current_user.id}

    if project_id:
        if project_id not in accessible_project_ids:
            raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this project.")
        for (uid,) in db.query(ProjectMember.user_id).filter(ProjectMember.project_id == project_id).all():
            member_user_ids.add(uid)
    else:
        if accessible_project_ids:
            for (uid,) in (
                db.query(ProjectMember.user_id)
                .filter(ProjectMember.project_id.in_(accessible_project_ids))
                .all()
            ):
                member_user_ids.add(uid)
        if current_user.org_id:
            org = db.query(Organization).filter(Organization.id == current_user.org_id).first()
            if org and not org.is_personal:
                for (uid,) in db.query(User.id).filter(User.org_id == org.id).all():
                    member_user_ids.add(uid)

    return (
        db.query(User)
        .filter(User.id.in_(list(member_user_ids)), User.is_active == True)  # noqa: E712
        .order_by(User.created_at.asc())
        .all()
    )


@router.get("/notifications")
def list_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )


@router.put("/notifications/{notif_id}/read")
def mark_notification_read(
    notif_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = (
        db.query(Notification)
        .filter(Notification.id == notif_id, Notification.user_id == current_user.id)
        .first()
    )
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.is_read = True
    db.commit()
    return {"status": "success", "id": notif_id}


@router.get("/activity")
def list_org_activity(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p_ids = get_user_accessible_project_ids(current_user, db)
    if project_id:
        if project_id not in p_ids:
            raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this project.")
        p_ids = [project_id]

    query = db.query(ActivityLog)
    if p_ids:
        query = query.filter((ActivityLog.project_id.in_(p_ids)) | (ActivityLog.user_id == current_user.id))
    else:
        query = query.filter(ActivityLog.user_id == current_user.id)

    return query.order_by(ActivityLog.created_at.desc()).limit(50).all()


@router.get("/settings")
def get_org_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    org = db.query(Organization).filter(Organization.id == current_user.org_id).first() if current_user.org_id else None
    stored_settings = (org.settings or {}) if org else {}
    return {
        "org_id": org.id if org else None,
        "org_name": org.name if org else f"{current_user.name}'s Organization",
        "primary_llm": settings.PRIMARY_LLM,
        "secondary_llm": settings.SECONDARY_LLM,
        "embedding_model": f"{ai_engine.effective_embedding_model} ({settings.EMBEDDING_DIMENSIONS} dim)",
        "database": "PostgreSQL + pgvector" if "postgres" in settings.DATABASE_URL else "SQLite (Local)",
        "evidence_verification_threshold": stored_settings.get("evidence_verification_threshold", 0.75),
        "require_security_approval": stored_settings.get("require_security_approval", False),
        "auto_approval_enabled": False,
        "notification_channels": stored_settings.get(
            "notification_channels",
            {"slack": False, "email": bool(settings.RESEND_API_KEY or settings.SMTP_HOST), "webhook": False},
        ),
    }


@router.put("/settings")
def update_org_settings(
    settings_in: Dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter(Organization.id == current_user.org_id).first() if current_user.org_id else None
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    if org.owner_id != current_user.id and normalize_role(current_user.role) != "org_admin":
        raise HTTPException(status_code=403, detail="Forbidden: Only organization admins can update org settings.")

    if "org_name" in settings_in:
        raw_name = settings_in["org_name"]
        if not isinstance(raw_name, str) or not raw_name.strip() or len(raw_name.strip()) > 120:
            raise HTTPException(status_code=400, detail="Organization name must be 1 to 120 characters.")
        org.name = raw_name.strip()

    merged = dict(org.settings or {})
    if "evidence_verification_threshold" in settings_in:
        val = settings_in["evidence_verification_threshold"]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not (0.0 <= float(val) <= 1.0):
            raise HTTPException(
                status_code=400,
                detail="evidence_verification_threshold must be a number between 0.0 and 1.0.",
            )
        merged["evidence_verification_threshold"] = round(float(val), 4)

    if "require_security_approval" in settings_in:
        val = settings_in["require_security_approval"]
        if not isinstance(val, bool):
            raise HTTPException(status_code=400, detail="require_security_approval must be a boolean.")
        merged["require_security_approval"] = val

    if "notification_channels" in settings_in:
        channels = settings_in["notification_channels"]
        if not isinstance(channels, dict):
            raise HTTPException(status_code=400, detail="notification_channels must be an object.")
        allowed_channels = {"slack", "email", "webhook"}
        sanitized_channels = dict(merged.get("notification_channels") or {})
        for ch_key, ch_val in channels.items():
            if ch_key not in allowed_channels or not isinstance(ch_val, bool):
                raise HTTPException(
                    status_code=400,
                    detail="notification_channels supports boolean flags for slack, email, and webhook only.",
                )
            sanitized_channels[ch_key] = ch_val
        merged["notification_channels"] = sanitized_channels

    org.settings = merged

    record_activity(
        db=db,
        action="organization.settings_updated",
        entity_type="organization",
        entity_id=org.id,
        user_id=current_user.id,
        org_id=org.id,
        actor_email=current_user.email,
        details={"message": f"Updated settings for {org.name}"},
    )
    db.commit()
    return {
        "status": "success",
        "message": "Organization settings updated successfully.",
        "settings": get_org_settings(current_user=current_user, db=db),
    }
