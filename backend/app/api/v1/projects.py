import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ALL_ROLES,
    create_personal_workspace_for_user,
    get_user_accessible_project_ids,
    get_user_project_role,
    normalize_role,
    verify_project_access,
)
from app.core.security import get_current_user
from app.models.evidence import Evidence
from app.models.integration import SourceRecord
from app.models.knowledge import Decision, RiskItem, TaskItem
from app.models.workspace import Project, ProjectMember, User, Workspace
from app.schemas.workspace import (
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.services.audit_service import create_notification, record_activity

router = APIRouter(prefix="/projects", tags=["Projects"])


def _build_project_response(p: Project, db: Session) -> ProjectResponse:
    m_count = db.query(func.count(ProjectMember.id)).filter(ProjectMember.project_id == p.id).scalar() or 0
    d_count = db.query(func.count(Decision.id)).filter(Decision.project_id == p.id).scalar() or 0
    t_count = db.query(func.count(TaskItem.id)).filter(TaskItem.project_id == p.id).scalar() or 0
    r_count = db.query(func.count(RiskItem.id)).filter(RiskItem.project_id == p.id).scalar() or 0
    e_count = db.query(func.count(Evidence.id)).filter(Evidence.project_id == p.id).scalar() or 0

    return ProjectResponse(
        id=p.id,
        workspace_id=p.workspace_id,
        name=p.name,
        slug=p.slug,
        description=p.description,
        status=p.status,
        priority=p.priority,
        tags=p.tags or [],
        created_at=p.created_at,
        updated_at=p.updated_at,
        member_count=m_count,
        decision_count=d_count,
        task_count=t_count,
        risk_count=r_count,
        evidence_count=e_count,
    )


@router.get("", response_model=List[ProjectResponse])
def list_projects(
    workspace_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    accessible_ids = get_user_accessible_project_ids(current_user, db)
    if not accessible_ids:
        return []

    query = db.query(Project).filter(Project.id.in_(accessible_ids))
    if workspace_id:
        query = query.filter(Project.workspace_id == workspace_id)

    projects = query.order_by(Project.created_at.desc()).all()
    return [_build_project_response(p, db) for p in projects]


@router.post("", response_model=ProjectResponse)
def create_project(
    project_in: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws = None
    if project_in.workspace_id:
        ws = db.query(Workspace).filter(Workspace.id == project_in.workspace_id).first()
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found.")
        if ws.owner_id != current_user.id and ws.org_id != current_user.org_id:
            raise HTTPException(status_code=403, detail="Forbidden: You cannot create projects in this workspace.")

    if not ws and current_user.personal_workspace_id:
        ws = db.query(Workspace).filter(Workspace.id == current_user.personal_workspace_id).first()

    if not ws:
        _, ws, _ = create_personal_workspace_for_user(current_user, db)

    slug = f"{project_in.name.lower().replace(' ', '-').replace('/', '-')}-{uuid.uuid4().hex[:4]}"
    p = Project(
        workspace_id=ws.id,
        creator_id=current_user.id,
        name=project_in.name.strip(),
        slug=slug,
        description=project_in.description,
        priority=project_in.priority or "medium",
        tags=project_in.tags or [],
        is_demo=False,
    )
    db.add(p)
    db.flush()

    pm = ProjectMember(
        project_id=p.id,
        user_id=current_user.id,
        project_role="project_owner",
        status="active",
    )
    db.add(pm)

    record_activity(
        db=db,
        action="project.created",
        entity_type="project",
        entity_id=p.id,
        user_id=current_user.id,
        project_id=p.id,
        org_id=ws.org_id,
        actor_email=current_user.email,
        details={"message": f"Created project '{p.name}'"},
    )
    db.commit()
    db.refresh(p)
    return _build_project_response(p, db)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = verify_project_access(project_id, current_user, db)
    return _build_project_response(p, db)


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    project_in: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = verify_project_access(project_id, current_user, db, require_admin=True)

    if project_in.name is not None:
        p.name = project_in.name.strip()
    if project_in.description is not None:
        p.description = project_in.description
    if project_in.status is not None:
        p.status = project_in.status
    if project_in.priority is not None:
        p.priority = project_in.priority
    if project_in.tags is not None:
        p.tags = project_in.tags

    record_activity(
        db=db,
        action="project.updated",
        entity_type="project",
        entity_id=p.id,
        user_id=current_user.id,
        project_id=p.id,
        actor_email=current_user.email,
        details={"message": f"Updated settings for project '{p.name}'"},
    )
    db.commit()
    db.refresh(p)
    return _build_project_response(p, db)


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = verify_project_access(project_id, current_user, db, require_admin=True)
    name = p.name
    record_activity(
        db=db,
        action="project.deleted",
        entity_type="project",
        entity_id=p.id,
        user_id=current_user.id,
        actor_email=current_user.email,
        details={"message": f"Deleted project '{name}'"},
    )
    db.delete(p)
    db.commit()
    return {"status": "success", "message": f"Project '{name}' deleted."}


@router.get("/{project_id}/timeline")
def get_project_timeline(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_project_access(project_id, current_user, db)
    timeline_events = []

    for d in db.query(Decision).filter(Decision.project_id == project_id).all():
        timeline_events.append({
            "id": f"dec-{d.id}",
            "type": "decision",
            "title": f"Decision: {d.title}",
            "author": d.decision_maker,
            "timestamp": f"{d.date}T10:00:00Z" if "T" not in (d.date or "") else d.date,
            "badge": d.status.upper(),
            "badge_color": "green",
            "description": d.summary,
        })

    for r in db.query(SourceRecord).filter(SourceRecord.project_id == project_id).all():
        ts = r.source_timestamp or r.ingested_at
        timeline_events.append({
            "id": f"rec-{r.id}",
            "type": r.source_type,
            "title": r.title,
            "author": r.author or "Contributor",
            "timestamp": ts.isoformat() if ts else "",
            "badge": r.source_type.replace("_", " ").upper(),
            "badge_color": "blue" if "github" in r.source_type else "purple",
            "description": r.content[:160] + "..." if len(r.content) > 160 else r.content,
            "url": r.url,
        })

    for t in db.query(TaskItem).filter(TaskItem.project_id == project_id).all():
        timeline_events.append({
            "id": f"task-{t.id}",
            "type": "task",
            "title": f"Task: {t.title}",
            "author": t.owner,
            "timestamp": t.created_at.isoformat() if t.created_at else "",
            "badge": t.priority.upper(),
            "badge_color": "red" if t.priority == "critical" else "amber",
            "description": t.description or "No description provided.",
        })

    timeline_events.sort(key=lambda x: x["timestamp"], reverse=True)
    return timeline_events


@router.get("/{project_id}/members", response_model=List[ProjectMemberResponse])
def get_project_members(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_project_access(project_id, current_user, db)
    members = db.query(ProjectMember).filter(ProjectMember.project_id == project_id).all()
    res = []
    for m in members:
        user = db.query(User).filter(User.id == m.user_id).first()
        res.append(
            ProjectMemberResponse(
                id=m.id,
                project_id=m.project_id,
                user_id=m.user_id,
                project_role=m.project_role,
                status=m.status,
                user_name=user.name if user else "Unknown User",
                user_email=user.email if user else "",
                joined_at=m.joined_at,
            )
        )
    return res


@router.post("/{project_id}/members", response_model=ProjectMemberResponse)
def add_project_member(
    project_id: str,
    member_in: ProjectMemberAdd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = verify_project_access(project_id, current_user, db, require_admin=True)
    normalized_member_role = normalize_role(member_in.project_role)
    if normalized_member_role not in ALL_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid project role '{member_in.project_role}'.")
    if normalized_member_role == "org_admin":
        raise HTTPException(
            status_code=400,
            detail="Organization admin ('org_admin') cannot be granted via project membership.",
        )

    actor_role = get_user_project_role(p, current_user, db)
    if normalized_member_role in {"project_owner", "workspace_owner"} and actor_role not in {
        "org_admin",
        "workspace_owner",
        "project_owner",
    }:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Only project or workspace owners can assign owner roles.",
        )

    target_user = None
    if member_in.user_id:
        target_user = db.query(User).filter(User.id == member_in.user_id).first()
    elif member_in.email:
        target_user = db.query(User).filter(User.email == member_in.email.strip().lower()).first()

    if not target_user:
        raise HTTPException(status_code=404, detail="User to add/invite was not found.")

    existing = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == target_user.id)
        .first()
    )

    if existing:
        existing.project_role = normalized_member_role
        existing.status = member_in.status
        pm = existing
    else:
        pm = ProjectMember(
            project_id=project_id,
            user_id=target_user.id,
            project_role=normalized_member_role,
            status=member_in.status,
        )
        db.add(pm)

    create_notification(
        db=db,
        user_id=target_user.id,
        project_id=p.id,
        title=f"Project Role Assigned: {p.name}",
        message=f"You were assigned role '{normalized_member_role}' on project '{p.name}'.",
        notif_type="info",
        link=f"/projects",
    )
    record_activity(
        db=db,
        action="project.member_updated",
        entity_type="project_member",
        entity_id=target_user.id,
        user_id=current_user.id,
        project_id=p.id,
        actor_email=current_user.email,
        details={"message": f"Set {target_user.email} role to {normalized_member_role} on {p.name}"},
    )
    db.commit()
    db.refresh(pm)
    return ProjectMemberResponse(
        id=pm.id,
        project_id=pm.project_id,
        user_id=pm.user_id,
        project_role=pm.project_role,
        status=pm.status,
        user_name=target_user.name,
        user_email=target_user.email,
        joined_at=pm.joined_at,
    )


@router.delete("/{project_id}/members/{user_id}")
def remove_project_member(
    project_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = verify_project_access(project_id, current_user, db, require_admin=True)
    if user_id == p.creator_id:
        raise HTTPException(status_code=400, detail="Cannot remove the project owner.")
    pm = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        .first()
    )
    if not pm:
        raise HTTPException(status_code=404, detail="Project membership not found.")
    db.delete(pm)
    record_activity(
        db=db,
        action="project.member_removed",
        entity_type="project_member",
        entity_id=user_id,
        user_id=current_user.id,
        project_id=project_id,
        actor_email=current_user.email,
        details={"message": f"Removed member {user_id} from project"},
    )
    db.commit()
    return {"status": "success", "message": "Project member removed."}
