import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import normalize_role
from app.core.security import get_current_user
from app.models.workspace import Organization, User, Workspace
from app.services.audit_service import create_notification, record_activity

router = APIRouter(prefix="/workspaces", tags=["Workspaces & Organizations"])


class WorkspaceCreateReq(BaseModel):
    name: str
    description: Optional[str] = None
    org_id: Optional[str] = None


class OrganizationCreateReq(BaseModel):
    name: str
    tier: Optional[str] = "team"


class OrganizationInviteReq(BaseModel):
    email: str
    role: Optional[str] = "developer"


def _verify_org_admin(org: Organization, user: User) -> None:
    is_owner = org.owner_id == user.id
    is_org_admin = user.org_id == org.id and normalize_role(user.role) == "org_admin"
    if not (is_owner or is_org_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Organization admin or owner privileges required.",
        )


@router.get("")
def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List workspaces owned by the user or non-personal workspaces in their organization."""
    workspaces = (
        db.query(Workspace)
        .filter(
            (Workspace.owner_id == current_user.id)
            | ((Workspace.org_id == current_user.org_id) & (Workspace.is_personal == False))  # noqa: E712
        )
        .all()
    )

    return [
        {
            "id": w.id,
            "name": w.name,
            "slug": w.slug,
            "description": w.description,
            "org_id": w.org_id,
            "is_personal": w.is_personal,
            "owner_id": w.owner_id,
            "created_at": w.created_at,
        }
        for w in workspaces
    ]


@router.post("")
def create_workspace(
    req: WorkspaceCreateReq,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new workspace within an organization the user owns or belongs to as admin."""
    org_id = req.org_id or current_user.org_id
    if org_id:
        org = db.query(Organization).filter(Organization.id == org_id).first()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found.")
        if org.owner_id != current_user.id and current_user.org_id != org.id:
            raise HTTPException(status_code=403, detail="Forbidden: You do not belong to this organization.")
    else:
        org = Organization(
            name=f"{current_user.name}'s Org",
            slug=f"org-{current_user.id[:8]}-{uuid.uuid4().hex[:4]}",
            owner_id=current_user.id,
        )
        db.add(org)
        db.flush()
        org_id = org.id
        current_user.org_id = org.id

    slug = f"{req.name.lower().replace(' ', '-').replace('/', '-')}-{uuid.uuid4().hex[:4]}"
    ws = Workspace(
        org_id=org_id,
        name=req.name.strip(),
        slug=slug,
        description=req.description,
        owner_id=current_user.id,
        is_personal=False,
    )
    db.add(ws)
    db.flush()
    record_activity(
        db=db,
        action="workspace.created",
        entity_type="workspace",
        entity_id=ws.id,
        user_id=current_user.id,
        org_id=org_id,
        actor_email=current_user.email,
        details={"message": f"Created workspace '{ws.name}'"},
    )
    db.commit()
    db.refresh(ws)

    return {
        "id": ws.id,
        "name": ws.name,
        "slug": ws.slug,
        "description": ws.description,
        "org_id": ws.org_id,
        "is_personal": ws.is_personal,
        "created_at": ws.created_at,
    }


@router.get("/organizations")
def list_organizations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    orgs = (
        db.query(Organization)
        .filter((Organization.owner_id == current_user.id) | (Organization.id == current_user.org_id))
        .all()
    )

    return [
        {
            "id": o.id,
            "name": o.name,
            "slug": o.slug,
            "tier": o.tier,
            "is_personal": o.is_personal,
            "is_owner": o.owner_id == current_user.id,
            "created_at": o.created_at,
        }
        for o in orgs
    ]


@router.post("/organizations")
def create_organization(
    req: OrganizationCreateReq,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    slug = f"{req.name.lower().replace(' ', '-').replace('/', '-')}-{uuid.uuid4().hex[:4]}"
    org = Organization(
        name=req.name.strip(),
        slug=slug,
        tier=req.tier or "team",
        owner_id=current_user.id,
        is_personal=False,
    )
    db.add(org)
    db.flush()

    ws = Workspace(
        org_id=org.id,
        name="General Workspace",
        slug="general",
        description="Default organization workspace",
        owner_id=current_user.id,
        is_personal=False,
    )
    db.add(ws)
    db.flush()

    if not current_user.org_id:
        current_user.org_id = org.id

    record_activity(
        db=db,
        action="organization.created",
        entity_type="organization",
        entity_id=org.id,
        user_id=current_user.id,
        org_id=org.id,
        actor_email=current_user.email,
        details={"message": f"Created organization '{org.name}'"},
    )
    db.commit()

    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "tier": org.tier,
        "workspace_id": ws.id,
        "created_at": org.created_at,
    }


@router.post("/organizations/{org_id}/invite")
def invite_to_organization(
    org_id: str,
    req: OrganizationInviteReq,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    _verify_org_admin(org, current_user)

    target_user = db.query(User).filter(User.email == req.email.strip().lower()).first()
    if not target_user:
        raise HTTPException(
            status_code=404,
            detail=f"User with email '{req.email}' not found. Ask them to register first.",
        )

    target_user.org_id = org.id
    target_user.role = req.role or "developer"

    create_notification(
        db=db,
        user_id=target_user.id,
        title=f"Added to {org.name}",
        message=f"{current_user.name} invited you to organization '{org.name}' as {target_user.role}.",
        notif_type="info",
        link="/team",
    )
    record_activity(
        db=db,
        action="organization.member_invited",
        entity_type="user",
        entity_id=target_user.id,
        user_id=current_user.id,
        org_id=org.id,
        actor_email=current_user.email,
        details={"message": f"Added {target_user.email} to {org.name} as {target_user.role}"},
    )
    db.commit()

    return {
        "status": "success",
        "message": f"User '{target_user.email}' added to organization '{org.name}' with role '{target_user.role}'.",
    }
