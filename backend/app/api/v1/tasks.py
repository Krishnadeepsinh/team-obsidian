from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_effective_project, get_user_accessible_project_ids, verify_project_access
from app.core.security import get_current_user
from app.models.knowledge import TaskItem
from app.models.workspace import User
from app.schemas.knowledge import TaskCreate, TaskResponse
from app.services.audit_service import record_activity

router = APIRouter(prefix="/tasks", tags=["Tasks & Responsibilities"])


@router.get("", response_model=List[TaskResponse])
def list_tasks(
    project_id: Optional[str] = None,
    departing_only: Optional[bool] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(TaskItem)
    if project_id:
        verify_project_access(project_id, current_user, db)
        query = query.filter(TaskItem.project_id == project_id)
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)
        if not p_ids:
            return []
        query = query.filter(TaskItem.project_id.in_(p_ids))

    if departing_only:
        query = query.filter(TaskItem.is_departing_owner == True)  # noqa: E712
    if status:
        query = query.filter(TaskItem.status == status)
    if priority:
        query = query.filter(TaskItem.priority == priority)
    return query.order_by(TaskItem.created_at.desc()).all()


@router.post("", response_model=TaskResponse)
def create_task(
    task_in: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    eff_proj = get_effective_project(task_in.project_id, current_user, db, require_write=True)
    if not eff_proj:
        raise HTTPException(status_code=400, detail="No accessible project found. Please create a project first.")

    t = TaskItem(
        project_id=eff_proj.id,
        created_by_user_id=current_user.id,
        title=task_in.title,
        description=task_in.description,
        owner=task_in.owner or current_user.name,
        priority=task_in.priority or "medium",
        status=task_in.status or "open",
        deadline=task_in.deadline,
        dependencies=task_in.dependencies or [],
        is_departing_owner=task_in.is_departing_owner or False,
        suggested_reassignment=task_in.suggested_reassignment,
        evidence_ids=task_in.evidence_ids or [],
        verification_status="Supported by Evidence" if task_in.evidence_ids else "Needs Human Verification",
        confidence=0.85 if task_in.evidence_ids else 0.5,
    )
    db.add(t)
    db.flush()
    record_activity(
        db=db,
        action="task.created",
        entity_type="task",
        entity_id=t.id,
        user_id=current_user.id,
        project_id=eff_proj.id,
        actor_email=current_user.email,
        details={"message": f"Created task '{t.title}' assigned to {t.owner}"},
    )
    db.commit()
    db.refresh(t)
    return t


@router.post("/{task_id}/reassign", response_model=TaskResponse)
def reassign_task(
    task_id: str,
    new_owner: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = db.query(TaskItem).filter(TaskItem.id == task_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    verify_project_access(t.project_id, current_user, db, require_write=True)

    prev_owner = t.owner
    t.owner = new_owner.strip()
    t.is_departing_owner = False
    t.suggested_reassignment = None
    record_activity(
        db=db,
        action="task.reassigned",
        entity_type="task",
        entity_id=t.id,
        user_id=current_user.id,
        project_id=t.project_id,
        actor_email=current_user.email,
        details={"message": f"Reassigned task '{t.title}' from {prev_owner} to {t.owner}"},
    )
    db.commit()
    db.refresh(t)
    return t


@router.put("/{task_id}/status", response_model=TaskResponse)
def update_task_status(
    task_id: str,
    status: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = db.query(TaskItem).filter(TaskItem.id == task_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    verify_project_access(t.project_id, current_user, db, require_write=True)
    t.status = status
    db.commit()
    db.refresh(t)
    return t
