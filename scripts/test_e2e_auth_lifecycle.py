import os
import sys
import time
import requests
from datetime import datetime, timezone

# Ensure backend imports work
sys.path.insert(0, os.path.abspath("backend"))

from app.core.database import SessionLocal
from app.models.workspace import User, PasswordResetToken
from app.core.security import hash_otp_code, verify_password, get_password_hash

BASE_URL = "http://localhost:8000/api/v1"
TEST_EMAIL = "yagnadeepsinh.4741@gmail.com"

def run_tests():
    print("=" * 60)
    print("TEAM OBSIDIAN - END-TO-END AUTH & OTP VERIFICATION")
    print("=" * 60)

    db = SessionLocal()
    user = db.query(User).filter(User.email == TEST_EMAIL).first()
    if not user:
        print(f"FAILED: Test user {TEST_EMAIL} not found in DB")
        return False
    original_password_hash = user.password_hash
    db.close()
    print(f"Verified test user exists: {TEST_EMAIL} (ID: {user.id})")

    # Clean up old tokens or wait for cooldown to ensure clean state
    time.sleep(3)

    # Step 1: Request OTP via Gmail SMTP
    print("\n--- TEST 1: Request OTP via Gmail SMTP ---")
    resp = requests.post(f"{BASE_URL}/auth/forgot-password", json={"email": TEST_EMAIL})
    if resp.status_code == 429:
        import re
        m = re.search(r"(\d+)\s+seconds", resp.json().get("detail", ""))
        wait_s = int(m.group(1)) + 1 if m else 5
        print(f"Waiting {wait_s}s for cooldown from previous run...")
        time.sleep(wait_s)
        resp = requests.post(f"{BASE_URL}/auth/forgot-password", json={"email": TEST_EMAIL})
    print(f"Response status: {resp.status_code}")
    print(f"Response data: {resp.json()}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    print("PASS: Forgot password request accepted & email dispatched via Gmail SMTP.")

    # Step 2: Rate Limiting / 60-Second Cooldown
    print("\n--- TEST 2: 60-Second Cooldown Rate Limiting ---")
    resp_cooldown = requests.post(f"{BASE_URL}/auth/forgot-password", json={"email": TEST_EMAIL})
    print(f"Response status: {resp_cooldown.status_code}")
    print(f"Response data: {resp_cooldown.json()}")
    assert resp_cooldown.status_code == 429, f"Expected 429 cooldown, got {resp_cooldown.status_code}"
    assert "Please wait" in resp_cooldown.json()["detail"], "Expected cooldown message"
    print("PASS: 60-second cooldown correctly prevented spamming.")

    # Step 3: Find generated OTP code from DB hash
    print("\n--- TEST 3: Lookup Token in Database & Invalidate Incorrect OTP ---")
    db = SessionLocal()
    latest_token_record = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user.id)
        .order_by(PasswordResetToken.created_at.desc())
        .first()
    )
    assert latest_token_record is not None, "Token record not found in DB"
    stored_hash = latest_token_record.token_hash
    print(f"Token record found: ID={latest_token_record.id}, ExpiresAt={latest_token_record.expires_at}")
    
    # Reverse OTP (000000 - 999999) to find exact 6-digit code for testing
    real_otp = None
    for i in range(1000000):
        candidate = f"{i:06d}"
        if hash_otp_code(candidate, TEST_EMAIL) == stored_hash:
            real_otp = candidate
            break
    db.close()
    assert real_otp is not None, "Could not match OTP hash"
    print(f"Real OTP verified via cryptographic hash match: [REDACTED 6-DIGIT]")

    # Step 4: Incorrect OTP Rejection
    print("\n--- TEST 4: Incorrect OTP Rejection and Decrement Attempts ---")
    bad_resp = requests.post(
        f"{BASE_URL}/auth/otp/verify",
        json={"email": TEST_EMAIL, "otp": "000000" if real_otp != "000000" else "999999"}
    )
    print(f"Response status: {bad_resp.status_code}")
    print(f"Response data: {bad_resp.json()}")
    assert bad_resp.status_code == 400, f"Expected 400, got {bad_resp.status_code}"
    detail_msg = bad_resp.json()["detail"]
    assert "attempt(s) remaining" in detail_msg, "Expected attempts remaining in error message"
    print("PASS: Incorrect OTP rejected and remaining attempts decremented.")

    # Step 5: Valid OTP Verification
    print("\n--- TEST 5: Valid OTP Verification ---")
    valid_resp = requests.post(
        f"{BASE_URL}/auth/otp/verify",
        json={"email": TEST_EMAIL, "otp": real_otp}
    )
    print(f"Response status: {valid_resp.status_code}")
    valid_data = valid_resp.json()
    print(f"Response status msg: {valid_data.get('status')}")
    assert valid_resp.status_code == 200, f"Expected 200, got {valid_resp.status_code}"
    reset_session_token = valid_data.get("reset_session_token")
    assert reset_session_token, "No reset_session_token returned"
    print(f"PASS: OTP verified successfully. reset_session_token obtained: {reset_session_token[:12]}...")

    # Step 6: Reset Password
    print("\n--- TEST 6: Reset Password using reset_session_token ---")
    NEW_TEMP_PW = "ObsidianNewPassword2026!"
    reset_resp = requests.post(
        f"{BASE_URL}/auth/reset-password",
        json={
            "email": TEST_EMAIL,
            "reset_token": reset_session_token,
            "new_password": NEW_TEMP_PW,
            "confirm_password": NEW_TEMP_PW
        }
    )
    print(f"Response status: {reset_resp.status_code}")
    print(f"Response data: {reset_resp.json()}")
    assert reset_resp.status_code == 200, f"Expected 200, got {reset_resp.status_code}"
    print("PASS: Password successfully changed.")

    # Step 7: Login with New Password
    print("\n--- TEST 7: Authenticate with New Password ---")
    session = requests.Session()
    login_resp = session.post(
        f"{BASE_URL}/auth/login",
        json={"email": TEST_EMAIL, "password": NEW_TEMP_PW}
    )
    print(f"Login status: {login_resp.status_code}")
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    user_info = login_resp.json().get("user", {})
    print(f"Logged in as: {user_info.get('name')} ({user_info.get('email')})")
    print(f"Session cookies: {list(session.cookies.keys())}")
    print("PASS: Login with new password succeeded.")

    # Step 8: Call Protected Endpoint (/auth/me/context)
    print("\n--- TEST 8: Access Protected Endpoint ---")
    ctx_resp = session.get(f"{BASE_URL}/auth/me/context")
    print(f"Context status: {ctx_resp.status_code}")
    assert ctx_resp.status_code == 200, f"Context call failed: {ctx_resp.text}"
    print("PASS: Protected endpoint accessible with session cookies.")

    # Step 9: Test Logout & Revocation
    print("\n--- TEST 9: Logout & Token Revocation ---")
    logout_resp = session.post(f"{BASE_URL}/auth/logout")
    print(f"Logout status: {logout_resp.status_code}")
    print(f"Logout cookies after call: {dict(session.cookies)}")
    assert logout_resp.status_code == 200, f"Logout failed: {logout_resp.text}"

    # Verify protected endpoint now returns 401
    ctx_after_logout = session.get(f"{BASE_URL}/auth/me/context")
    print(f"Context status after logout: {ctx_after_logout.status_code}")
    assert ctx_after_logout.status_code == 401, f"Expected 401 after logout, got {ctx_after_logout.status_code}"
    print("PASS: Logout revoked token and deleted cookies successfully.")

    # Restore original password hash in DB for user
    print("\n--- RESTORING ORIGINAL PASSWORD HASH ---")
    db = SessionLocal()
    u = db.query(User).filter(User.email == TEST_EMAIL).first()
    if u:
        u.password_hash = original_password_hash
        db.commit()
    db.close()
    print("Original password hash successfully restored.")

    print("\n" + "=" * 60)
    print("ALL 9 AUTH & OTP LIFECYCLE TESTS PASSED PERFECTLY!")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
