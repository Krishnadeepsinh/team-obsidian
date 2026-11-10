import base64
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db, set_rls_user_context

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


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT token using PyJWT."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.setdefault("token_type", "access")
    to_encode.update({
        "iat": int(now.timestamp()),
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


def hash_reset_token(token: str) -> str:
    """Hash a password reset token with SHA-256 before database persistence."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Strict Bearer JWT dependency. Never silently falls back to unauthenticated access."""
    from app.models.workspace import User

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header. Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    if not payload or not payload.get("sub") or payload.get("token_type", "access") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired or token is invalid. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or has been deactivated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    set_rls_user_context(db, user.id)
    return user
