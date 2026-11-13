import uuid
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.main import app
from app.models.workspace import Organization, User
from app.services.ai_engine import AIEngine
from app.services.email_service import EmailService

init_db()
client = TestClient(app)


def test_email_service_url_encoding_and_resend_sandbox_classification(tmp_path, monkeypatch):
    svc = EmailService()
    svc._outbox_path = tmp_path / "outbox.log"

    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    monkeypatch.setattr(settings, "SMTP_USER", "")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "")
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "noreply@teamobsidian.local")
    monkeypatch.setattr(settings, "APP_ENV", "development")

    assert svc.is_resend_sandbox_only() is True
    assert svc.delivery_mode() == "resend_sandbox"

    fake_resp = MagicMock()
    fake_resp.status_code = 403
    fake_resp.text = '{"message":"You can only send testing emails to your own email address."}'

    with patch("app.services.email_service.requests.post", return_value=fake_resp) as post_mock:
        res = svc.send_password_reset_email("alice+ops@example.com", "tok+123", user_name="Alice")

    assert res["delivered"] is False
    assert res["provider"] == "dev_outbox"
    assert res["attempted_provider"] == "resend"
    assert res["error_code"] == "resend_sandbox_restricted"

    sent_payload = post_mock.call_args.kwargs["json"]
    assert "email=alice%2Bops%40example.com" in sent_payload["text"]
    assert "token=tok%2B123" in sent_payload["text"]
    assert "Reset code: tok+123" in svc._outbox_path.read_text(encoding="utf-8")


def test_forgot_password_reports_sandbox_warning_without_exposing_token(monkeypatch):
    email = f"forgot_{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Reset Tester",
            "email": email,
            "password": "StrongPassword2026!",
            "role": "developer",
        },
    )
    assert reg.status_code == 200, reg.text
    org_id = reg.json()["user"]["org_id"]

    try:
        monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_key")
        monkeypatch.setattr(settings, "SMTP_HOST", "")
        monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "")
        monkeypatch.setattr(settings, "APP_ENV", "development")

        caps = client.get("/api/v1/auth/capabilities")
        assert caps.status_code == 200
        assert caps.json()["email_delivery_mode"] == "resend_sandbox"
        assert caps.json()["email_sandbox_only"] is True

        fake_resp = MagicMock()
        fake_resp.status_code = 403
        fake_resp.text = "You can only send testing emails to your own email address."
        with patch("app.services.email_service.requests.post", return_value=fake_resp):
            forgot = client.post("/api/v1/auth/forgot-password", json={"email": email})

        assert forgot.status_code == 200
        body = forgot.json()
        assert "reset_token" not in body
        assert body["delivery_provider"] == "dev_outbox"
        assert "sandbox sender" in body["delivery_warning"]
    finally:
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.email == email).first()
            if u:
                db.delete(u)
            org = db.query(Organization).filter(Organization.id == org_id).first()
            if org:
                db.delete(org)
            db.commit()
        finally:
            db.close()


def test_ai_engine_429_cooldown_and_extractive_synthesis():
    engine = AIEngine()
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")
    engine._genai_client = fake_client

    docs = [
        {
            "source_title": "ADR-014 Payment Gateway Timeout Fix",
            "source_type": "github",
            "source_url": "https://github.com/org/repo/pull/14",
            "author": "Priya Patel",
            "verification_status": "Verified by Reviewer",
            "relevance_score": 0.91,
            "excerpt": "Reduced Stripe webhook retry timeout from 30s to 8s with idempotency keys to avoid worker starvation. Fallback queues failed charges to Redis DLQ.",
        },
        {
            "source_title": "Runbook: Incident Response Checkout",
            "source_type": "confluence",
            "source_url": "https://confluence.internal/checkout",
            "author": "Rahul Mehta",
            "verification_status": "Supported by Evidence",
            "relevance_score": 0.84,
            "excerpt": "On-call engineers must inspect the Redis DLQ before replaying Stripe webhook events during checkout incidents.",
        },
    ]

    first = engine.answer_question("How are Stripe webhook timeouts handled during checkout?", docs)
    assert first["is_grounded"] is True
    assert "### Evidence Summary" in first["answer"]
    assert "[Evidence 1]" in first["answer"]
    assert "[Evidence 2]" in first["answer"]
    assert first["confidence_breakdown"]["total_citations"] == 2
    assert first["confidence_breakdown"]["verified_citations"] == 2
    assert first["confidence_breakdown"]["distinct_sources"] == 2
    assert first["confidence_breakdown"]["independent_sources"] == 2
    assert "Obsidian Intelligence Engine" in first["model_used"] or first["model_used"].endswith("(Extractive Synthesis)")
    calls_after_first = fake_client.models.generate_content.call_count
    assert calls_after_first >= 1

    # Second call should short-circuit via per-model cooldown cache without calling generate_content again
    second = engine.answer_question("Who owns the Stripe webhook DLQ runbook?", docs)
    assert second["is_grounded"] is True
    assert fake_client.models.generate_content.call_count == calls_after_first

