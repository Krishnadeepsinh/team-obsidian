import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Optional
import requests

from app.core.config import settings

logger = logging.getLogger("team_obsidian.email")


class EmailService:
    """Delivers password reset and invitation emails via Resend, SMTP, or safe local dev outbox."""

    def __init__(self):
        self._outbox_path = Path(__file__).resolve().parent.parent.parent / ".dev_mail_outbox.log"

    def is_configured(self) -> bool:
        return bool(
            settings.RESEND_API_KEY
            or (settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)
        )

    def send_email(self, to_email: str, subject: str, html_body: str, text_body: str) -> dict:
        if settings.RESEND_API_KEY:
            try:
                res = requests.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": settings.SMTP_FROM_EMAIL or "TEAM OBSIDIAN <noreply@teamobsidian.local>",
                        "to": [to_email],
                        "subject": subject,
                        "html": html_body,
                        "text": text_body,
                    },
                    timeout=10,
                )
                if 200 <= res.status_code < 300:
                    return {"delivered": True, "provider": "resend"}
                logger.warning("Resend email delivery failed (%s): %s", res.status_code, res.text)
            except Exception as exc:
                logger.warning("Resend email exception: %s", exc)

        if settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD:
            try:
                msg = EmailMessage()
                msg["Subject"] = subject
                msg["From"] = settings.SMTP_FROM_EMAIL or settings.SMTP_USER
                msg["To"] = to_email
                msg.set_content(text_body)
                msg.add_alternative(html_body, subtype="html")
                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                    server.starttls()
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.send_message(msg)
                return {"delivered": True, "provider": "smtp"}
            except Exception as exc:
                logger.warning("SMTP email delivery failed: %s", exc)

        # Development/test outbox fallback (never exposes token in API response)
        if settings.APP_ENV != "production":
            try:
                with self._outbox_path.open("a", encoding="utf-8") as fh:
                    fh.write(f"--- TO: {to_email} | SUBJECT: {subject} ---\n{text_body}\n\n")
            except Exception:
                pass
            logger.info("Recorded email in dev outbox for %s (%s)", to_email, subject)
            return {"delivered": False, "provider": "dev_outbox"}

        return {"delivered": False, "provider": "unconfigured"}

    def send_password_reset_email(self, to_email: str, reset_token: str, user_name: Optional[str] = None) -> dict:
        reset_link = f"{settings.FRONTEND_URL}/forgot-password?token={reset_token}&email={to_email}"
        greeting = f"Hi {user_name}," if user_name else "Hello,"
        text_body = (
            f"{greeting}\n\n"
            "We received a request to reset your TEAM OBSIDIAN password.\n"
            f"Reset link (expires in {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes, single-use):\n"
            f"{reset_link}\n\n"
            f"Reset code: {reset_token}\n\n"
            "If you did not request this, you can safely ignore this email."
        )
        html_body = (
            f"<p>{greeting}</p>"
            "<p>We received a request to reset your <strong>TEAM OBSIDIAN</strong> password.</p>"
            f"<p><a href=\"{reset_link}\">Reset Password</a> (expires in {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes)</p>"
            "<p>If you did not request this, you can safely ignore this email.</p>"
        )
        return self.send_email(
            to_email=to_email,
            subject="TEAM OBSIDIAN — Password Reset Request",
            html_body=html_body,
            text_body=text_body,
        )


email_service = EmailService()

