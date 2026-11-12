import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Optional
import requests

from app.core.config import settings

logger = logging.getLogger("team_obsidian.email")


class EmailService:
    """Delivers transactional password resets, handover sign-off requests, and drift alerts via Resend or SMTP."""

    def __init__(self):
        self._outbox_path = Path(__file__).resolve().parent.parent.parent / ".dev_mail_outbox.log"

    def is_configured(self) -> bool:
        return bool(
            settings.RESEND_API_KEY
            or (settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)
        )

    def send_email(self, to_email: str, subject: str, html_body: str, text_body: str) -> dict:
        if not to_email or "@" not in to_email:
            return {"delivered": False, "provider": "invalid_recipient"}

        if settings.RESEND_API_KEY:
            try:
                res = requests.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": (
                            settings.SMTP_FROM_EMAIL
                            if settings.SMTP_FROM_EMAIL and not settings.SMTP_FROM_EMAIL.lower().endswith(".local")
                            else "TEAM OBSIDIAN <onboarding@resend.dev>"
                        ),
                        "to": [to_email],
                        "subject": subject,
                        "html": html_body,
                        "text": text_body,
                    },
                    timeout=10,
                )
                if 200 <= res.status_code < 300:
                    return {"delivered": True, "provider": "resend"}
                logger.warning("Resend email delivery failed (%s): %s", res.status_code, res.text[:200])
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

    def send_handover_review_email(
        self,
        to_email: str,
        reviewer_name: str,
        handover_title: str,
        project_name: str,
        role: str,
    ) -> dict:
        approvals_url = f"{settings.FRONTEND_URL}/handover/approvals"
        text_body = (
            f"Hi {reviewer_name},\n\n"
            f"You have been requested to review and sign off on handover dossier '{handover_title}' "
            f"for project '{project_name}' as {role}.\n\n"
            f"Review & Sign Off: {approvals_url}\n"
        )
        html_body = (
            f"<p>Hi {reviewer_name},</p>"
            f"<p>You have been requested to review and sign off on handover dossier "
            f"<strong>{handover_title}</strong> for project <strong>{project_name}</strong> as <em>{role}</em>.</p>"
            f"<p><a href=\"{approvals_url}\">Open Handover Approvals</a></p>"
        )
        return self.send_email(
            to_email=to_email,
            subject=f"TEAM OBSIDIAN — Sign-Off Requested: {handover_title}",
            html_body=html_body,
            text_body=text_body,
        )

    def send_drift_alert_email(
        self,
        to_email: str,
        recipient_name: str,
        project_name: str,
        target_title: str,
        drift_summary: str,
        severity: str = "high",
    ) -> dict:
        evidence_url = f"{settings.FRONTEND_URL}/evidence"
        text_body = (
            f"Hi {recipient_name},\n\n"
            f"[{severity.upper()} KNOWLEDGE DRIFT] Detected in project '{project_name}':\n"
            f"Target: {target_title}\n"
            f"Details: {drift_summary}\n\n"
            f"Audit in Evidence Center: {evidence_url}\n"
        )
        html_body = (
            f"<p>Hi {recipient_name},</p>"
            f"<p><strong>[{severity.upper()} KNOWLEDGE DRIFT]</strong> Detected in project <strong>{project_name}</strong>:</p>"
            f"<p><strong>Target:</strong> {target_title}<br/><strong>Details:</strong> {drift_summary}</p>"
            f"<p><a href=\"{evidence_url}\">Inspect Drift in Evidence Center</a></p>"
        )
        return self.send_email(
            to_email=to_email,
            subject=f"TEAM OBSIDIAN — Knowledge Drift Alert ({severity.upper()}): {project_name}",
            html_body=html_body,
            text_body=text_body,
        )


email_service = EmailService()
