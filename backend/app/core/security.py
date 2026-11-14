import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Cookie, Depends, Header, HTTPException, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, get_db, set_rls_user_context

logger = logging.getLogger("obsidian.security")

# Argon2id password hasher (OWASP recommended parameters)
_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

# Legacy static-salt SHA-256 verification only for transparent migration of pre-existing users
_LEGACY_SALT = "obsidian_salt_enterprise_2026"


def get_password_hash(password: str) -> str:
    """Hash a password using Argon2id."""
    return _ph.hash(password)


def _is_legacy_sha256_hash(hashed_password: str) -> bool:
    if not hashed_password or len(hashed_password) != 64:
        return False
    return all(c in "0123456789abcdef" for c in hashed_password.lower())


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against Argon2id hash (with legacy SHA-256 fallback for migration)."""
    if not plain_password or not hashed_password:
        return False
    if hashed_password.startswith("$argon2"):
        try:
            return _ph.verify(hashed_password, plain_password)
        except (VerifyMismatchError, InvalidHashError):
            return False
    if _is_legacy_sha256_hash(hashed_password):
        legacy = hashlib.sha256(f"{_LEGACY_SALT}_{plain_password}".encode()).hexdigest()
        return hmac.compare_digest(legacy, hashed_password)
    return False


def verify_and_upgrade_password(plain_password: str, user: Any, db: Session) -> bool:
    """Verify password and transparently upgrade legacy SHA-256 hashes to Argon2id on login."""
    if not verify_password(plain_password, user.password_hash):
        return False
    if not user.password_hash.startswith("$argon2") or _ph.check_needs_rehash(user.password_hash):
        user.password_hash = get_password_hash(plain_password)
        db.commit()
    return True


def _get_fernet() -> Fernet:
    """Build Fernet cipher from CREDENTIALS_ENCRYPTION_KEY or derive deterministically from SECRET_KEY in dev."""
    raw = settings.CREDENTIALS_ENCRYPTION_KEY
    if raw:
        return Fernet(raw.encode("utf-8"))
    if settings.APP_ENV == "production":
        raise RuntimeError("CREDENTIALS_ENCRYPTION_KEY is required in production.")
    derived = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest())
    return Fernet(derived)


def encrypt_credentials(creds: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Encrypt integration credentials dict at rest using Fernet."""
    if not creds:
        return {}
    if "__encrypted__" in creds:
        return creds
    f = _get_fernet()
    plaintext = json.dumps(creds).encode("utf-8")
    token = f.encrypt(plaintext).decode("utf-8")
    return {"__encrypted__": token, "v": 1}


def decrypt_credentials(stored: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Decrypt stored integration credentials dict (supports legacy plaintext dicts safely)."""
    if not stored or not isinstance(stored, dict):
        return {}
    enc = stored.get("__encrypted__")
    if not enc:
        return stored
    try:
        f = _get_fernet()
        plaintext = f.decrypt(enc.encode("utf-8")).decode("utf-8")
        data = json.loads(plaintext)
        return data if isinstance(data, dict) else {}
    except (InvalidToken, ValueError, TypeError):
        return {}


def mask_credentials(creds: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return strictly masked credential metadata safe for API responses."""
    decrypted = decrypt_credentials(creds)
    if not decrypted:
        return {"has_token": False}
    masked: Dict[str, Any] = {}
    for k, v in decrypted.items():
        if isinstance(v, str) and len(v) > 8:
            masked[k] = f"{v[:4]}****{v[-4:]}"
        else:
            masked[k] = "****"
    masked["has_token"] = bool(
        decrypted.get("token")
        or decrypted.get("access_token")
        or decrypted.get("api_key")
        or decrypted.get("bot_token")
    )
    return masked


# Thread-safe L1 cache + DB-persisted JWT JTI revocation store (survives worker restarts & multi-worker scaling)
_REVOKED_JTIS: Dict[str, float] = {}
_REVOKED_LOCK = threading.Lock()


def clear_revoked_jti_cache() -> None:
    """Clear only the in-memory L1 JTI revocation cache (DB rows remain enforced)."""
    with _REVOKED_LOCK:
        _REVOKED_JTIS.clear()


def revoke_token_jti(
    jti: Optional[str],
    exp_ts: Optional[float] = None,
    db: Optional[Session] = None,
) -> None:
    """Revoke a JWT JTI in L1 cache and persist it to the database until expiration."""
    if not jti:
        return
    now = time.time()
    expiry = float(exp_ts) if exp_ts else (now + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    with _REVOKED_LOCK:
        expired = [k for k, v in _REVOKED_JTIS.items() if v < now]
        for k in expired:
            _REVOKED_JTIS.pop(k, None)
        _REVOKED_JTIS[jti] = expiry

    from app.models.workspace import RevokedToken

    own_session = db is None
    session = db if db is not None else SessionLocal()
    try:
        session.query(RevokedToken).filter(RevokedToken.expires_ts < now).delete(synchronize_session=False)
        session.merge(RevokedToken(jti=jti, expires_ts=expiry))
        if own_session:
            session.commit()
        else:
            session.flush()
    except SQLAlchemyError as exc:
        logger.warning("Failed to persist JTI revocation in database: %s", exc)
        if own_session:
            session.rollback()
    finally:
        if own_session:
            session.close()


def is_token_jti_revoked(jti: Optional[str], db: Optional[Session] = None) -> bool:
    """Check whether a JWT JTI has been revoked (L1 cache with DB fallback)."""
    if not jti:
        return False
    now = time.time()
    with _REVOKED_LOCK:
        exp_ts = _REVOKED_JTIS.get(jti)
        if exp_ts is not None:
            if exp_ts >= now:
                return True
            _REVOKED_JTIS.pop(jti, None)

    from app.models.workspace import RevokedToken

    own_session = db is None
    session = db if db is not None else SessionLocal()
    try:
        rec = session.query(RevokedToken).filter(RevokedToken.jti == jti).first()
        if not rec:
            return False
        if float(rec.expires_ts) < now:
            session.delete(rec)
            if own_session:
                session.commit()
            else:
                session.flush()
            return False
        with _REVOKED_LOCK:
            _REVOKED_JTIS[jti] = float(rec.expires_ts)
        return True
    except SQLAlchemyError as exc:
        logger.warning("Failed to check JTI revocation in database: %s", exc)
        return False
    finally:
        if own_session:
            session.close()


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT token using PyJWT with sub-second precision iat."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.setdefault("token_type", "access")
    to_encode.update({
        "iat": round(now.timestamp(), 6),
        "exp": int(expire.timestamp()),
        "jti": str(uuid.uuid4()),
    })
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_oauth_state_token(payload: Dict[str, Any], expires_minutes: int = 15) -> str:
    """Create a short-lived signed OAuth state token bound to user/project."""
    data = payload.copy()
    data["token_type"] = "oauth_state"
    return create_access_token(data, expires_delta=timedelta(minutes=expires_minutes))


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate JWT signature & expiration using PyJWT."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"require": ["exp"]},
        )
        return payload
    except jwt.PyJWTError:
        return None


def generate_reset_token() -> str:
    """Generate a high-entropy single-use password reset token."""
    return secrets.token_urlsafe(32)


def generate_otp_code() -> str:
    """Generate a cryptographically secure 6-digit numeric OTP code."""
    # 000000 to 999999
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp_code(otp: str, email: str = "") -> str:
    """Hash an OTP code with SHA-256 bound to recipient email."""
    normalized_email = (email or "").strip().lower()
    raw = f"obsidian_otp_{normalized_email}_{otp.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_otp_session_token() -> str:
    """Generate a high-entropy verified session token returned after OTP verification."""
    return f"otp_sess_{secrets.token_urlsafe(32)}"


def hash_reset_token(token: str) -> str:
    """Hash a password reset token with SHA-256 before database persistence."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def set_auth_cookie(response: Response, token: str) -> None:
    """Attach signed HttpOnly session cookie with strict SameSite/Secure policy."""
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=bool(settings.COOKIE_SECURE or settings.APP_ENV == "production"),
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Clear HttpOnly session cookie consistently across browsers."""
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path="/",
        secure=bool(settings.COOKIE_SECURE or settings.APP_ENV == "production"),
        samesite=settings.COOKIE_SAMESITE,
        httponly=True,
    )


def get_current_user(
    authorization: Optional[str] = Header(None),
    session_cookie: Optional[str] = Cookie(None, alias=settings.AUTH_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    """Strict Bearer JWT (or signed HttpOnly cookie fallback) dependency."""
    from app.models.workspace import User

    token: Optional[str] = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif session_cookie:
        token = session_cookie.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header. Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(token)
    if not payload or not payload.get("sub") or payload.get("token_type", "access") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired or token is invalid. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if is_token_jti_revoked(payload.get("jti"), db=db):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been signed out. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or has been deactivated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    pw_updated = getattr(user, "password_updated_at", None)
    if pw_updated is not None:
        if pw_updated.tzinfo is None:
            pw_updated = pw_updated.replace(tzinfo=timezone.utc)
        pw_ts = pw_updated.timestamp()
        tok_iat = payload.get("iat")
        try:
            tok_iat_f = float(tok_iat) if tok_iat is not None else 0.0
        except (TypeError, ValueError):
            tok_iat_f = 0.0
        if tok_iat_f + 0.001 < pw_ts:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session invalidated after password update. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    set_rls_user_context(db, user.id)
    return user
