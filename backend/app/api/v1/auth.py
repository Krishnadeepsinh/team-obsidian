from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import (
    ALL_ROLES,
    create_personal_workspace_for_user,
    get_user_accessible_projects,
    normalize_role,
)
from app.core.rate_limiter import get_client_ip, rate_limiter
from app.core.security import (
    clear_auth_cookie,
    create_access_token,
    decode_access_token,
    generate_otp_code,
    generate_otp_session_token,
    generate_reset_token,
    get_current_user,
    get_password_hash,
    hash_otp_code,
    hash_reset_token,
    revoke_token_jti,
    set_auth_cookie,
    verify_and_upgrade_password,
    verify_password,
)
from app.models.workspace import Organization, PasswordResetToken, User, Workspace
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ResetPasswordWithOtpRequest,
    Token,
    UserLogin,
    UserProfileUpdate,
    UserRegister,
    UserResponse,
    VerifyOtpRequest,
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
def register(user_in: UserRegister, request: Request, response: Response, db: Session = Depends(get_db)):
    rate_limiter.check(
        f"register:{get_client_ip(request)}",
        limit=60,
        window_seconds=300,
        detail="Too many registration attempts. Please try again later.",
    )
    normalized_email = user_in.email.strip().lower()
    existing = db.query(User).filter(User.email == normalized_email).first()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists.")

    requested_role = normalize_role(user_in.role or "developer")
    if requested_role not in ALL_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{user_in.role}'. Allowed roles: {', '.join(sorted(ALL_ROLES))}",
        )
    if requested_role == "org_admin":
        raise HTTPException(
            status_code=400,
            detail="Cannot self-assign 'org_admin' during public registration.",
        )

    user = User(
        name=user_in.name.strip(),
        email=normalized_email,
        role=requested_role,
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
    if settings.AUTH_COOKIE_ENABLED or request.headers.get("x-use-session-cookie") == "1":
        set_auth_cookie(response, token)
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
def login(login_in: UserLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = get_client_ip(request)
    normalized_email = login_in.email.strip().lower()
    fail_key = f"login_fail:{ip}:{normalized_email}"
    rate_limiter.check(
        f"login_ip:{ip}",
        limit=60,
        window_seconds=60,
        detail="Too many login attempts from this network. Please retry shortly.",
    )
    rate_limiter.check(
        fail_key,
        limit=10,
        window_seconds=60,
        detail="Too many failed login attempts for this account. Please wait a minute before retrying.",
    )
    user = db.query(User).filter(User.email == normalized_email).first()
    if not user or not verify_and_upgrade_password(login_in.password, user, db):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    rate_limiter.reset_key(fail_key)
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
    if settings.AUTH_COOKIE_ENABLED or request.headers.get("x-use-session-cookie") == "1":
        set_auth_cookie(response, token)
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
    response: Response,
    db: Session = Depends(get_db),
):
    """Sign out active session, revoke token JTI, and clear session cookie across all browsers."""
    clear_auth_cookie(response)
    auth_header = request.headers.get("authorization", "")
    raw_tok = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else (request.cookies.get(settings.AUTH_COOKIE_NAME) or "").strip()
    user_id = None
    user_email = None
    org_id = None

    if raw_tok:
        payload = decode_access_token(raw_tok)
        if payload:
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti:
                revoke_token_jti(jti, exp, db=db)
                db.commit()
            user_id = payload.get("sub")
            user_email = payload.get("email")

    if user_id:
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                org_id = user.org_id
            record_activity(
                db=db,
                action="auth.logout",
                entity_type="user",
                entity_id=user_id,
                user_id=user_id,
                org_id=org_id,
                actor_email=user_email,
                details={"message": f"Signed out session for {user_email or user_id}"},
                ip_address=request.client.host if request.client else None,
            )
            db.commit()
        except Exception:
            pass

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
        "email_delivery_mode": email_service.delivery_mode(),
        "email_sandbox_only": email_service.is_resend_sandbox_only(),
        "smtp_configured": email_service.is_smtp_configured(),
        "supabase_storage_configured": storage_service.is_supabase_storage_configured(),
        "oauth_providers": {
            "github": bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET),
            "slack": bool(settings.SLACK_CLIENT_ID and settings.SLACK_CLIENT_SECRET),
            "notion": bool(settings.NOTION_CLIENT_ID and settings.NOTION_CLIENT_SECRET),
            "jira": bool((settings.JIRA_CLIENT_ID or settings.ATLASSIAN_CLIENT_ID) and (settings.JIRA_CLIENT_SECRET or settings.ATLASSIAN_CLIENT_SECRET)),
            "confluence": bool((settings.CONFLUENCE_CLIENT_ID or settings.ATLASSIAN_CLIENT_ID) and (settings.CONFLUENCE_CLIENT_SECRET or settings.ATLASSIAN_CLIENT_SECRET)),
            "linear": bool(settings.LINEAR_CLIENT_ID and settings.LINEAR_CLIENT_SECRET),
            "gitlab": bool(settings.GITLAB_CLIENT_ID and settings.GITLAB_CLIENT_SECRET),
            "sentry": bool(settings.SENTRY_CLIENT_ID and settings.SENTRY_CLIENT_SECRET),
        },
    }


@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Create a cryptographically secure 6-digit email OTP and deliver via Gmail SMTP or fallback provider."""
    ip = get_client_ip(request)
    normalized_email = req.email.strip().lower()
    rate_limiter.check(
        f"forgot:{ip}:{normalized_email}",
        limit=8,
        window_seconds=300,
        detail="Too many verification requests. Please try again later.",
    )
    if settings.APP_ENV == "production" and not email_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Password recovery email delivery is not configured on this deployment. "
                "Signed-in users can update their password under Profile."
            ),
        )

    user = db.query(User).filter(User.email == normalized_email).first()
    delivery_result = None
    now = datetime.now(timezone.utc)

    if user and user.is_active:
        # Check 60-second resend cooldown against recent active OTP
        recent_token = (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
            .order_by(PasswordResetToken.created_at.desc())
            .first()
        )
        if recent_token and recent_token.created_at:
            created_at = recent_token.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            elapsed_seconds = (now - created_at).total_seconds()
            if elapsed_seconds < 60:
                wait_time = int(60 - elapsed_seconds)
                raise HTTPException(
                    status_code=429,
                    detail=f"Please wait {wait_time} seconds before requesting a new verification code.",
                )

        # Invalidate any prior unused tokens for this user
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        ).update({"used_at": now})

        # Generate 6-digit numeric OTP and hash bound to email
        raw_otp = generate_otp_code()
        otp_hash = hash_otp_code(raw_otp, user.email)

        token_rec = PasswordResetToken(
            user_id=user.id,
            token_hash=otp_hash,
            expires_at=now + timedelta(minutes=5),  # 5-minute expiration
            attempts_count=0,
        )
        db.add(token_rec)
        record_activity(
            db=db,
            action="auth.otp_requested",
            entity_type="user",
            entity_id=user.id,
            user_id=user.id,
            org_id=user.org_id,
            actor_email=user.email,
            details={"message": "Password reset 6-digit OTP code dispatched"},
            ip_address=ip,
        )
        db.commit()
        delivery_result = email_service.send_otp_email(user.email, raw_otp, user_name=user.name)

    response_payload: Dict[str, Any] = {
        "status": "success",
        "message": "If this email is registered, a 6-digit verification code has been dispatched.",
        "cooldown_seconds": 60,
        "expires_in_minutes": 5,
    }
    if delivery_result:
        response_payload["delivered"] = delivery_result.get("delivered", False)
        response_payload["delivery_provider"] = delivery_result.get("provider")
        if delivery_result.get("warning"):
            response_payload["delivery_warning"] = delivery_result.get("warning")
        elif delivery_result.get("error_code") == "resend_sandbox_restricted":
            response_payload["delivery_warning"] = (
                "Email provider is in sandbox sender mode; check terminal outbox or configure verified domain."
            )

    return response_payload


@router.post("/otp/verify")
def verify_otp(req: VerifyOtpRequest, request: Request, db: Session = Depends(get_db)):
    """Verify single-use 6-digit OTP against stored hash, enforcing 5-min expiry and max 5 attempts."""
    ip = get_client_ip(request)
    normalized_email = req.email.strip().lower()
    clean_otp = req.otp.strip()

    rate_limiter.check(
        f"otp_verify:{ip}:{normalized_email}",
        limit=10,
        window_seconds=300,
        detail="Too many verification attempts. Please wait a few minutes.",
    )

    user = db.query(User).filter(User.email == normalized_email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code.")

    now = datetime.now(timezone.utc)
    token_rec = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        .order_by(PasswordResetToken.created_at.desc())
        .first()
    )

    if not token_rec:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code. Please request a new one.")

    # Check maximum attempt limit (5 attempts)
    if (token_rec.attempts_count or 0) >= 5:
        token_rec.used_at = now
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Maximum verification attempts (5) exceeded. This code has been invalidated.",
        )

    # Check expiration (5 minutes)
    expires_at = token_rec.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        token_rec.used_at = now
        db.commit()
        raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new one.")

    # Compare cryptographic hash
    expected_hash = hash_otp_code(clean_otp, user.email)
    import hmac
    if not hmac.compare_digest(token_rec.token_hash, expected_hash):
        token_rec.attempts_count = (token_rec.attempts_count or 0) + 1
        db.commit()
        remaining = max(0, 5 - token_rec.attempts_count)
        if remaining == 0:
            token_rec.used_at = now
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="Maximum verification attempts (5) exceeded. Please request a new code.",
            )
        raise HTTPException(
            status_code=400,
            detail=f"Incorrect verification code. {remaining} attempt(s) remaining.",
        )

    # Valid OTP verified! Issue single-use reset session token
    session_token = generate_otp_session_token()
    token_rec.reset_session_token = session_token
    token_rec.verified_at = now
    db.commit()

    return {
        "status": "success",
        "message": "Verification code confirmed successfully.",
        "reset_session_token": session_token,
    }


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Reset password after successful OTP verification, enforcing password requirements and revoking prior sessions."""
    ip = get_client_ip(request)
    normalized_email = req.email.strip().lower()
    rate_limiter.check(
        f"reset:{ip}:{normalized_email}",
        limit=8,
        window_seconds=300,
        detail="Too many password reset attempts. Please wait a few minutes.",
    )
    user = db.query(User).filter(User.email == normalized_email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset session.")

    if req.confirm_password and req.new_password != req.confirm_password:
        raise HTTPException(status_code=400, detail="New password and confirm password do not match.")

    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")

    provided_token = req.reset_token.strip()
    now = datetime.now(timezone.utc)

    # Match by reset_session_token (verified OTP session) OR direct hash fallback
    token_rec = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
            (
                (PasswordResetToken.reset_session_token == provided_token)
                | (PasswordResetToken.token_hash == hash_reset_token(provided_token))
                | (PasswordResetToken.token_hash == hash_otp_code(provided_token, user.email))
            ),
        )
        .first()
    )

    if not token_rec:
        raise HTTPException(status_code=400, detail="Invalid, expired, or already-used reset token. Please request a new code.")

    expires_at = token_rec.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now and not token_rec.verified_at:
        token_rec.used_at = now
        db.commit()
        raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new one.")

    # Invalidate token immediately
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
        details={"message": "Password updated via verified 6-digit email OTP"},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {
        "status": "success",
        "message": "Password has been successfully updated. You may now log in with your new password.",
    }


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rate_limiter.check(
        f"chgpwd:{current_user.id}",
        limit=10,
        window_seconds=300,
        detail="Too many password change attempts. Please wait a few minutes.",
    )
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
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        payload = decode_access_token(auth_header[7:].strip())
        if payload:
            revoke_token_jti(payload.get("jti"), payload.get("exp"), db=db)
            db.commit()

    accessible_projects = get_user_accessible_projects(current_user, db)
    active_project_id = accessible_projects[0].id if accessible_projects else None
    new_token = create_access_token({
        "sub": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
        "workspace_id": current_user.personal_workspace_id,
        "project_id": active_project_id,
    })
    return {
        "status": "success",
        "message": "Password updated successfully.",
        "access_token": new_token,
        "token_type": "bearer",
    }


@router.put("/me", response_model=UserResponse)
def update_profile(
    profile_in: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if profile_in.name is not None:
        clean_name = profile_in.name.strip()
        if not clean_name:
            raise HTTPException(status_code=400, detail="Display name cannot be empty.")
        current_user.name = clean_name
    if profile_in.title is not None:
        current_user.title = profile_in.title.strip()
    if profile_in.department is not None:
        current_user.department = profile_in.department.strip()
    if profile_in.avatar_url is not None:
        raw_avatar = profile_in.avatar_url.strip()
        if raw_avatar:
            if len(raw_avatar) > 500 or raw_avatar.startswith("//"):
                raise HTTPException(status_code=400, detail="Invalid avatar URL.")
            parsed = urlparse(raw_avatar)
            if parsed.scheme:
                if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
                    raise HTTPException(status_code=400, detail="Avatar URL must use http or https.")
            elif not raw_avatar.startswith("/"):
                raise HTTPException(status_code=400, detail="Avatar URL must be an https URL or relative path.")
        current_user.avatar_url = raw_avatar or None
    db.commit()
    db.refresh(current_user)
    return current_user
