import uuid
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import SessionLocal, init_db
from app.core.security import get_password_hash, hash_otp_code
from app.models.workspace import User, Organization, Workspace, PasswordResetToken

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    init_db()


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_user(db_session: Session):
    suffix = uuid.uuid4().hex[:6]
    email = f"security_login_{suffix}@teamobsidian.local"
    org = Organization(name=f"Login OTP Org {suffix}", slug=f"login-otp-org-{suffix}")
    db_session.add(org)
    db_session.flush()

    ws = Workspace(name=f"Login Workspace {suffix}", slug=f"login-ws-{suffix}", org_id=org.id)
    db_session.add(ws)
    db_session.flush()

    user = User(
        name="Security Tester",
        email=email,
        password_hash=get_password_hash("ValidPass123!"),
        org_id=org.id,
        personal_workspace_id=ws.id,
        role="developer",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_login_otp_flow(test_user, db_session: Session):
    """Verify complete 2-step login OTP verification flow."""
    # Step 1: Login with credentials (pass x-skip-otp: 0 to force production OTP flow)
    res = client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "ValidPass123!"},
        headers={"x-skip-otp": "0"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data.get("otp_required") is True
    assert "access_token" not in data
    assert "@" in data.get("masked_email", "")

    # Check OTP record created in database with purpose login_verification
    token_rec = (
        db_session.query(PasswordResetToken)
        .filter(
            PasswordResetToken.user_id == test_user.id,
            PasswordResetToken.purpose == "login_verification",
            PasswordResetToken.used_at.is_(None),
        )
        .first()
    )
    assert token_rec is not None
    assert token_rec.purpose == "login_verification"

    # Step 2: Attempt verification with incorrect OTP code
    fail_res = client.post(
        "/api/v1/auth/login/verify-otp",
        json={"email": test_user.email, "otp": "000000"},
    )
    assert fail_res.status_code == 400
    assert "Incorrect" in fail_res.json().get("detail", "")

    # Step 3: Verify with correct OTP
    raw_code = "829143"
    token_rec.token_hash = hash_otp_code(raw_code, test_user.email)
    db_session.commit()

    success_res = client.post(
        "/api/v1/auth/login/verify-otp",
        json={"email": test_user.email, "otp": raw_code},
    )
    assert success_res.status_code == 200
    success_data = success_res.json()
    assert "access_token" in success_data
    assert success_data["user"]["email"] == test_user.email


def test_login_otp_strict_separation_from_password_reset(test_user, db_session: Session):
    """
    CRITICAL: Verify that login verification OTPs can NEVER be used for password reset,
    and password reset OTPs can NEVER be used for login verification.
    """
    # Create a password_reset token
    pw_raw = "112233"
    pw_token = PasswordResetToken(
        user_id=test_user.id,
        token_hash=hash_otp_code(pw_raw, test_user.email),
        purpose="password_reset",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        attempts_count=0,
    )
    db_session.add(pw_token)

    # Create a login_verification token
    login_raw = "445566"
    login_token = PasswordResetToken(
        user_id=test_user.id,
        token_hash=hash_otp_code(login_raw, test_user.email),
        purpose="login_verification",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        attempts_count=0,
    )
    db_session.add(login_token)
    db_session.commit()

    # 1. Attempt to use password_reset code for login verification -> MUST FAIL
    res1 = client.post(
        "/api/v1/auth/login/verify-otp",
        json={"email": test_user.email, "otp": pw_raw},
    )
    assert res1.status_code == 400

    # 2. Attempt to use login_verification code for password reset -> MUST FAIL
    res2 = client.post(
        "/api/v1/auth/otp/verify",
        json={"email": test_user.email, "otp": login_raw},
    )
    assert res2.status_code == 400


def test_login_otp_expiration(test_user, db_session: Session):
    """Expired login verification OTP must be rejected."""
    raw_code = "998877"
    token = PasswordResetToken(
        user_id=test_user.id,
        token_hash=hash_otp_code(raw_code, test_user.email),
        purpose="login_verification",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        attempts_count=0,
    )
    db_session.add(token)
    db_session.commit()

    res = client.post(
        "/api/v1/auth/login/verify-otp",
        json={"email": test_user.email, "otp": raw_code},
    )
    assert res.status_code == 400
    assert "expired" in res.json().get("detail", "").lower()


def test_login_otp_max_attempts_lockout(test_user, db_session: Session):
    """After 5 failed attempts, the OTP is invalidated and locked out."""
    raw_code = "123456"
    token = PasswordResetToken(
        user_id=test_user.id,
        token_hash=hash_otp_code(raw_code, test_user.email),
        purpose="login_verification",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        attempts_count=4,
    )
    db_session.add(token)
    db_session.commit()

    # 5th failed attempt
    res = client.post(
        "/api/v1/auth/login/verify-otp",
        json={"email": test_user.email, "otp": "000000"},
    )
    assert res.status_code == 400
    assert "exceeded" in res.json().get("detail", "").lower()

    # Token should now be marked used
    db_session.refresh(token)
    assert token.used_at is not None
