from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import create_personal_workspace_for_user, get_user_accessible_projects
from app.core.security import (
    create_access_token,
    generate_reset_token,
    get_current_user,
    get_password_hash,
    hash_reset_token,
    verify_and_upgrade_password,
    verify_password,
)
from app.models.workspace import Organization, PasswordResetToken, User, Workspace
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    Token,
    UserLogin,
    UserProfileUpdate,
    UserRegister,
    UserResponse,
)
from app.services.audit_service import record_activity
from app.services.email_service import email_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


def require_roles(allowed_roles: list):
    """Factory dependency for role-based access control (RBAC)."""
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Action requires one of roles {allowed_roles}.",
            )
        return current_user
    return role_checker


@router.post("/register", response_model=Token)
def register(user_in: UserRegister, request: Request, db: Session = Depends(get_db)):
    normalized_email = user_in.email.strip().lower()
    existing = db.query(User).filter(User.email == normalized_email).first()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists.")

    user = User(
        name=user_in.name.strip(),
        email=normalized_email,
        role=user_in.role or "developer",
        title=user_in.title,
        department=user_in.department,
        password_hash=get_password_hash(user_in.password),
        password_updated_at=datetime.now(timezone.utc),
        last_login_at=datetime.now(timezone.utc),
        is_active=True,
    )
    db.add(user)
    db.flush()

    org, ws, proj = create_personal_workspace_for_user(user, db)
    record_activity(
        db=db,
        action="auth.registered",
        entity_type="user",
        entity_id=user.id,
        user_id=user.id,
        project_id=proj.id,
        org_id=org.id,
        actor_email=user.email,
        details={"message": f"Registered new workspace and starter project for {user.name}"},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(user)

    token = create_access_token({
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "workspace_id": ws.id,
        "project_id": proj.id,
    })
    return {
        "access_token": token,
        "token_type": "bearer",
        "personal_workspace_id": ws.id,
        "active_project_id": proj.id,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "title": user.title,
            "department": user.department,
            "org_id": org.id,
            "personal_workspace_id": ws.id,
            "active_project_id": proj.id,
        },
    }


@router.post("/login", response_model=Token)
def login(login_in: UserLogin, request: Request, db: Session = Depends(get_db)):
    normalized_email = login_in.email.strip().lower()
    user = db.query(User).filter(User.email == normalized_email).first()
    if not user or not verify_and_upgrade_password(login_in.password, user, db):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account has been deactivated.")

    if not user.personal_workspace_id:
        create_personal_workspace_for_user(user, db)

    user.last_login_at = datetime.now(timezone.utc)
    accessible_projects = get_user_accessible_projects(user, db)
    active_project_id = accessible_projects[0].id if accessible_projects else None

    record_activity(
        db=db,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        user_id=user.id,
        project_id=active_project_id,
        org_id=user.org_id,
        actor_email=user.email,
        details={"message": f"Authenticated session started for {user.email}"},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(user)

    token = create_access_token({
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "workspace_id": user.personal_workspace_id,
        "project_id": active_project_id,
    })
    return {
        "access_token": token,
        "token_type": "bearer",
        "personal_workspace_id": user.personal_workspace_id,
        "active_project_id": active_project_id,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "title": user.title,
            "department": user.department,
            "org_id": user.org_id,
            "personal_workspace_id": user.personal_workspace_id,
            "active_project_id": active_project_id,
        },
    }


@router.post("/logout")
def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record_activity(
        db=db,
        action="auth.logout",
        entity_type="user",
        entity_id=current_user.id,
        user_id=current_user.id,
        org_id=current_user.org_id,
        actor_email=current_user.email,
        details={"message": f"Signed out session for {current_user.email}"},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"status": "success", "message": "Signed out successfully."}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/me/context")
def get_user_context(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve all accessible workspaces, organizations, and projects for context switching."""
    accessible_projects = get_user_accessible_projects(current_user, db)

    workspaces = (
        db.query(Workspace)
        .filter(
            (Workspace.owner_id == current_user.id)
            | ((Workspace.org_id == current_user.org_id) & (Workspace.is_personal == False))  # noqa: E712
        )
        .all()
    )

    orgs = (
        db.query(Organization)
        .filter((Organization.owner_id == current_user.id) | (Organization.id == current_user.org_id))
        .all()
    )

    return {
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "role": current_user.role,
            "title": current_user.title,
            "department": current_user.department,
            "org_id": current_user.org_id,
            "personal_workspace_id": current_user.personal_workspace_id,
        },
        "workspaces": [
            {"id": w.id, "name": w.name, "slug": w.slug, "org_id": w.org_id, "is_personal": w.is_personal}
            for w in workspaces
        ],
        "organizations": [
            {
                "id": o.id,
                "name": o.name,
                "slug": o.slug,
                "is_personal": o.is_personal,
                "tier": o.tier,
            }
            for o in orgs
        ],
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "slug": p.slug,
                "workspace_id": p.workspace_id,
                "status": p.status,
                "is_demo": bool(getattr(p, "is_demo", False)),
            }
            for p in accessible_projects
        ],
        "active_project_id": accessible_projects[0].id if accessible_projects else None,
    }


@router.get("/capabilities")
def get_auth_capabilities() -> Dict[str, Any]:
    """Report non-sensitive runtime capabilities for password recovery email, storage, and OAuth providers."""
    from app.services.storage_service import storage_service

    return {
        "app_env": settings.APP_ENV,
        "email_delivery_configured": email_service.is_configured(),
        "supabase_storage_configured": storage_service.is_supabase_storage_configured(),
        "oauth_providers": {
            "github": bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET),
            "slack": bool(settings.SLACK_CLIENT_ID and settings.SLACK_CLIENT_SECRET),
            "notion": bool(settings.NOTION_CLIENT_ID and settings.NOTION_CLIENT_SECRET),
        },
    }


@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Create a single-use hashed password reset token and deliver via email. Never returns token in HTTP response."""
    if settings.APP_ENV == "production" and not email_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Password recovery email delivery is not configured on this deployment "
                "(RESEND_API_KEY or SMTP credentials required). Signed-in users can update their password under Profile."
            ),
        )
    normalized_email = req.email.strip().lower()
    user = db.query(User).filter(User.email == normalized_email).first()
    if user and user.is_active:
        # Invalidate any prior unused reset tokens for this user
        now = datetime.now(timezone.utc)
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        ).update({"used_at": now})

        raw_token = generate_reset_token()
        token_rec = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_reset_token(raw_token),
            expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
        )
        db.add(token_rec)
        record_activity(
            db=db,
            action="auth.password_reset_requested",
            entity_type="user",
            entity_id=user.id,
            user_id=user.id,
            org_id=user.org_id,
            actor_email=user.email,
            details={"message": "Password reset link issued"},
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        email_service.send_password_reset_email(user.email, raw_token, user_name=user.name)

    return {
        "status": "success",
        "message": "If this email is registered, password reset instructions have been sent.",
    }


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Verify single-use expiring password reset token and update password."""
    normalized_email = req.email.strip().lower()
    user = db.query(User).filter(User.email == normalized_email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")

    token_hash = hash_reset_token(req.reset_token.strip())
    token_rec = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.token_hash == token_hash,
        )
        .first()
    )

    now = datetime.now(timezone.utc)
    if not token_rec or token_rec.used_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or already-used reset token.")

    expires_at = token_rec.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        raise HTTPException(status_code=400, detail="Reset token has expired. Please request a new one.")

    token_rec.used_at = now
    user.password_hash = get_password_hash(req.new_password)
    user.password_updated_at = now

    record_activity(
        db=db,
        action="auth.password_reset_completed",
        entity_type="user",
        entity_id=user.id,
        user_id=user.id,
        org_id=user.org_id,
        actor_email=user.email,
        details={"message": "Password updated via one-time reset token"},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"status": "success", "message": "Password has been successfully updated. You may now log in."}


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(req.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    now = datetime.now(timezone.utc)
    current_user.password_hash = get_password_hash(req.new_password)
    current_user.password_updated_at = now
    record_activity(
        db=db,
        action="auth.password_changed",
        entity_type="user",
        entity_id=current_user.id,
        user_id=current_user.id,
        org_id=current_user.org_id,
        actor_email=current_user.email,
        details={"message": "User updated account password"},
    )
    db.commit()
    return {"status": "success", "message": "Password updated successfully."}


@router.put("/me", response_model=UserResponse)
def update_profile(
    profile_in: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if profile_in.name is not None:
        current_user.name = profile_in.name.strip()
    if profile_in.title is not None:
        current_user.title = profile_in.title
    if profile_in.department is not None:
        current_user.department = profile_in.department
    if profile_in.avatar_url is not None:
        current_user.avatar_url = profile_in.avatar_url
    db.commit()
    db.refresh(current_user)
    return current_user
