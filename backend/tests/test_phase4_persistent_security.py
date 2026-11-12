import uuid
from fastapi.testclient import TestClient

from app.core.database import SessionLocal, init_db
from app.core.rate_limiter import rate_limiter
from app.core.security import clear_revoked_jti_cache, decode_access_token
from app.main import app
from app.models.workspace import Organization, RateLimitEvent, RevokedToken, User

init_db()
client = TestClient(app)


def _register(prefix: str = "p4sec"):
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@phase4-test.io"
    password = "StrongPhase4Password2026!"
    res = client.post(
        "/api/v1/auth/register",
        json={
            "name": f"{prefix.title()} Engineer",
            "email": email,
            "password": password,
            "role": "developer",
            "title": "Engineer",
            "department": "Security",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    return {
        "email": email,
        "password": password,
        "token": data["access_token"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
        "user_id": data["user"]["id"],
    }


def _cleanup(email: str, *jtis: str):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        if u:
            org = db.query(Organization).filter(Organization.id == u.org_id).first() if u.org_id else None
            if org:
                db.delete(org)
            db.delete(u)
        for jti in jtis:
            if jti:
                db.query(RevokedToken).filter(RevokedToken.jti == jti).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_phase4_jti_revocation_survives_memory_cache_reset():
    """Revoked JWTs must remain blocked (401) even after in-memory L1 cache is cleared."""
    ctx = _register(prefix="p4jti")
    jti_1 = (decode_access_token(ctx["token"]) or {}).get("jti")
    jti_2 = None

    try:
        assert client.get("/api/v1/auth/me", headers=ctx["headers"]).status_code == 200

        # Logout revokes JTI in both L1 cache and DB
        r_out = client.post("/api/v1/auth/logout", headers=ctx["headers"])
        assert r_out.status_code == 200

        # Simulate process restart / second worker with empty RAM cache
        clear_revoked_jti_cache()

        db = SessionLocal()
        try:
            row = db.query(RevokedToken).filter(RevokedToken.jti == jti_1).first()
            assert row is not None
        finally:
            db.close()

        r_blocked = client.get("/api/v1/auth/me", headers=ctx["headers"])
        assert r_blocked.status_code == 401

        # Log back in and verify change-password also persists JTI revocation cleanly
        r_login = client.post(
            "/api/v1/auth/login",
            json={"email": ctx["email"], "password": ctx["password"]},
        )
        assert r_login.status_code == 200
        tok2 = r_login.json()["access_token"]
        jti_2 = (decode_access_token(tok2) or {}).get("jti")

        r_chg = client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {tok2}"},
            json={"current_password": ctx["password"], "new_password": "UpdatedPhase4Password2026!"},
        )
        assert r_chg.status_code == 200, r_chg.text
        tok3 = r_chg.json()["access_token"]

        clear_revoked_jti_cache()
        assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok2}"}).status_code == 401
        assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok3}"}).status_code == 200
    finally:
        clear_revoked_jti_cache()
        _cleanup(ctx["email"], jti_1, jti_2)


def test_phase4_rate_limiter_persists_across_memory_reset():
    """Brute-force 429 enforcement must survive clearing L1 in-memory rate-limit buckets."""
    ctx = _register(prefix="p4rl")
    rate_limiter.clear()

    try:
        for _ in range(10):
            r_fail = client.post(
                "/api/v1/auth/login",
                json={"email": ctx["email"], "password": "IncorrectPassword2026!"},
            )
            assert r_fail.status_code == 401

        # Confirm DB rows exist, then wipe RAM buckets to simulate worker restart
        db = SessionLocal()
        try:
            count = (
                db.query(RateLimitEvent)
                .filter(RateLimitEvent.bucket_key.like(f"login_fail:%:{ctx['email']}"))
                .count()
            )
            assert count == 10
        finally:
            db.close()

        rate_limiter.clear_memory_only()

        r_throttled = client.post(
            "/api/v1/auth/login",
            json={"email": ctx["email"], "password": "IncorrectPassword2026!"},
        )
        assert r_throttled.status_code == 429
        assert "Retry-After" in r_throttled.headers

        # Verify reset_key removes persisted DB failure events for that bucket
        rate_limiter.reset_key(f"login_fail:127.0.0.1:{ctx['email']}")
        rate_limiter.reset_key(f"login_fail:testclient:{ctx['email']}")
        r_ok = client.post(
            "/api/v1/auth/login",
            json={"email": ctx["email"], "password": ctx["password"]},
        )
        assert r_ok.status_code == 200
    finally:
        rate_limiter.clear()
        _cleanup(ctx["email"])

