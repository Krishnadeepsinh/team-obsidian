from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from app.models.workspace import ActivityLog, Notification


def record_activity(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: str,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    org_id: Optional[str] = None,
    actor_email: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> ActivityLog:
    """Create a structured multi-tenant audit log record."""
    log = ActivityLog(
        project_id=project_id,
        user_id=user_id,
        org_id=org_id,
        actor_email=actor_email,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
        ip_address=ip_address,
    )
    db.add(log)
    return log


def create_notification(
    db: Session,
    user_id: str,
    title: str,
    message: str,
    notif_type: str = "info",
    link: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Notification:
    """Create a user-scoped notification."""
    notif = Notification(
        user_id=user_id,
        project_id=project_id,
        title=title,
        message=message,
        type=notif_type,
        link=link,
        is_read=False,
    )
    db.add(notif)
    return notif

