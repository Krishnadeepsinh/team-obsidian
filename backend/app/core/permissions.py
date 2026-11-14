from typing import List, Optional, Tuple
from sqlalchemy import or_
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.workspace import User, Project, Workspace, Organization, ProjectMember

ALL_ROLES = {
    "org_admin",
    "workspace_owner",
    "project_owner",
    "project_manager",
    "tech_lead",
    "developer",
    "departing_employee",
    "incoming_employee",
    "viewer",
    # Backwards-compatible role aliases
    "admin",
    "owner",
    "pm",
    "qa",
    "reviewer",
    "departing",
    "incoming",
}

ROLE_ALIASES = {
    "admin": "org_admin",
    "owner": "project_owner",
    "pm": "project_manager",
    "departing": "departing_employee",
    "incoming": "incoming_employee",
}

PROJECT_ADMIN_ROLES = {"org_admin", "workspace_owner", "project_owner", "project_manager", "tech_lead"}
WRITE_ROLES = PROJECT_ADMIN_ROLES | {"developer", "departing_employee", "incoming_employee", "qa", "reviewer"}
APPROVER_ROLES = PROJECT_ADMIN_ROLES | {"departing_employee", "incoming_employee", "reviewer"}


def normalize_role(role: Optional[str]) -> str:
    r = (role or "developer").strip().lower()
    return ROLE_ALIASES.get(r, r)


def get_user_accessible_project_ids(user: User, db: Session) -> List[str]:
    """Retrieve all project IDs accessible by the authenticated user in batched queries."""
    if not user:
        return []

    norm_user_role = normalize_role(user.role)
    is_org_admin = norm_user_role in {"org_admin", "admin"}

    ws_conditions = [Workspace.owner_id == user.id]
    if user.org_id and is_org_admin:
        ws_conditions.append((Workspace.org_id == user.org_id) & (Workspace.is_personal == False))

    user_ws = [w[0] for w in db.query(Workspace.id).filter(or_(*ws_conditions)).all()]

    member_pids = [
        pm[0]
        for pm in db.query(ProjectMember.project_id)
        .filter(
            ProjectMember.user_id == user.id,
            ProjectMember.status.in_(["active", "departing", "incoming"]),
        )
        .all()
    ]

    proj_conditions = [Project.creator_id == user.id]
    if user_ws:
        proj_conditions.append(Project.workspace_id.in_(user_ws))
    if member_pids:
        proj_conditions.append(Project.id.in_(member_pids))

    p_ids = [p[0] for p in db.query(Project.id).filter(or_(*proj_conditions)).all()]
    return list(set(p_ids))


def get_user_accessible_projects(user: User, db: Session) -> List[Project]:
    p_ids = get_user_accessible_project_ids(user, db)
    if not p_ids:
        return []
    return db.query(Project).filter(Project.id.in_(p_ids)).all()


def check_user_project_access(project: Project, user: User, db: Session) -> Optional[str]:
    """Check if user has access to project and return their effective role, or None if forbidden."""
    if not user or not project:
        return None

    # 1. Project creator has direct owner access (0 extra queries)
    if project.creator_id == user.id:
        return "project_owner"

    # 2. Project membership (indexed query)
    member = (
        db.query(ProjectMember)
        .filter(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
            ProjectMember.status.in_(["active", "departing", "incoming"]),
        )
        .first()
    )
    if member:
        return normalize_role(member.project_role)

    # 3. Workspace ownership (indexed query)
    ws = db.query(Workspace).filter(Workspace.id == project.workspace_id).first()
    if ws and ws.owner_id == user.id:
        return "workspace_owner"

    # 4. Organization admin/owner access (non-personal workspaces)
    if user.org_id and ws and not ws.is_personal and ws.org_id == user.org_id:
        norm_user_role = normalize_role(user.role)
        org = db.query(Organization).filter(Organization.id == user.org_id).first()
        if org and not getattr(org, "is_personal", False) and (org.owner_id == user.id or norm_user_role in {"org_admin", "admin"}):
            return "org_admin"

    return None


def get_user_project_role(project: Project, user: User, db: Session) -> str:
    role = check_user_project_access(project, user, db)
    return role if role is not None else normalize_role(user.role)


def verify_project_access(
    project_id: str,
    user: User,
    db: Session,
    required_roles: Optional[set] = None,
    require_write: bool = False,
    require_admin: bool = False,
) -> Project:
    """Validate project existence, tenant isolation, and RBAC permission with minimal database round trips."""
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID '{project_id}' not found.",
        )

    eff_role = check_user_project_access(proj, user, db)
    if eff_role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You do not have access to this project.",
        )

    if require_admin and eff_role not in PROJECT_ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Project administrator or owner role required for this action.",
        )

    if require_write and eff_role not in WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Read-only viewer role cannot modify project data.",
        )

    if required_roles:
        normalized_required = {normalize_role(r) for r in required_roles}
        if eff_role not in normalized_required and eff_role != "org_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Action requires one of roles {sorted(normalized_required)}.",
            )

    return proj


def get_effective_project(
    project_id: Optional[str],
    user: User,
    db: Session,
    require_write: bool = False,
) -> Optional[Project]:
    clean_pid = (project_id or "").strip()
    if clean_pid and clean_pid.lower() != "default":
        return verify_project_access(clean_pid, user, db, require_write=require_write)
    accessible = get_user_accessible_projects(user, db)
    if accessible:
        # Prefer non-demo project if available
        non_demo = [p for p in accessible if not getattr(p, "is_demo", False)]
        proj = non_demo[0] if non_demo else accessible[0]
        if require_write:
            verify_project_access(proj.id, user, db, require_write=True)
        return proj
    return None


def create_personal_workspace_for_user(
    user: User,
    db: Session,
) -> Tuple[Organization, Workspace, Project]:
    """Provision an isolated personal Organization, Workspace, and starter Project for a new user."""
    uid_suffix = user.id[:8]
    clean_name = user.name.strip() if user.name else "User"

    org = Organization(
        name=f"{clean_name}'s Organization",
        slug=f"org-{uid_suffix}",
        tier="standard",
        owner_id=user.id,
        is_personal=True,
    )
    db.add(org)
    db.flush()

    ws = Workspace(
        org_id=org.id,
        name="Personal Workspace",
        slug=f"workspace-{uid_suffix}",
        description=f"Private personal workspace for {clean_name}",
        owner_id=user.id,
        is_personal=True,
    )
    db.add(ws)
    db.flush()

    proj = Project(
        workspace_id=ws.id,
        creator_id=user.id,
        name=f"{clean_name}'s Project",
        slug=f"project-{uid_suffix}",
        description="Private engineering project repository and knowledge base.",
        status="active",
        priority="medium",
        tags=["Personal", "Active"],
        is_demo=False,
    )
    db.add(proj)
    db.flush()

    member = ProjectMember(
        project_id=proj.id,
        user_id=user.id,
        project_role="project_owner",
        status="active",
    )
    db.add(member)

    user.org_id = org.id
    user.personal_workspace_id = ws.id
    db.flush()

    return org, ws, proj
