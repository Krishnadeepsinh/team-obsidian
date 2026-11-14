import html
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode
import requests

from app.core.config import settings

logger = logging.getLogger("team_obsidian.email")


class EmailService:
    """Delivers transactional password resets, handover sign-off requests, and drift alerts via Resend or SMTP."""

    def __init__(self):
        self._outbox_path = Path(__file__).resolve().parent.parent.parent / ".dev_mail_outbox.log"

    def is_smtp_configured(self) -> bool:
        return bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)

    def has_custom_sender_domain(self) -> bool:
        sender = (settings.SMTP_FROM_EMAIL or "").strip().lower()
        public_freemail_domains = (
            "@gmail.com",
            "@googlemail.com",
            "@yahoo.com",
            "@hotmail.com",
            "@outlook.com",
            "@live.com",
            "@icloud.com",
            "@proton.me",
            "@protonmail.com",
        )
        return bool(
            sender
            and "@" in sender
            and not sender.endswith(".local")
            and "resend.dev" not in sender
            and not any(sender.endswith(dom) for dom in public_freemail_domains)
        )

    def is_resend_sandbox_only(self) -> bool:
        """True when only Resend is configured and sender falls back to onboarding@resend.dev sandbox."""
        return bool(settings.RESEND_API_KEY) and not self.is_smtp_configured() and not self.has_custom_sender_domain()

    def delivery_mode(self) -> str:
        if self.is_smtp_configured():
            return "smtp"
        if settings.RESEND_API_KEY:
            return "resend_verified" if self.has_custom_sender_domain() else "resend_sandbox"
        return "dev_outbox" if settings.APP_ENV != "production" else "unconfigured"

    def is_configured(self) -> bool:
        return bool(settings.RESEND_API_KEY or self.is_smtp_configured())

    def send_email(self, to_email: str, subject: str, html_body: str, text_body: str) -> dict:
        if not to_email or "@" not in to_email:
            return {"delivered": False, "provider": "invalid_recipient"}

        attempted_provider: Optional[str] = None
        error_code: Optional[str] = None
        error_detail: Optional[str] = None

        # 1. Primary Cloud Priority: HTTPS Mail Relay on Vercel
        # Bypasses cloud host outbound SMTP port restrictions (e.g. Render Free Tier blocks 25, 465, 587)
        if settings.FRONTEND_URL and settings.FRONTEND_URL.startswith("https://"):
            relay_url = f"{settings.FRONTEND_URL.rstrip('/')}/api/mail/send"
            try:
                res = requests.post(
                    relay_url,
                    headers={
                        "Authorization": f"Bearer {settings.SECRET_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "to": to_email,
                        "subject": subject,
                        "html": html_body,
                        "text": text_body,
                        "from": f"TEAM OBSIDIAN <{settings.SMTP_FROM_EMAIL or settings.SMTP_USER}>",
                    },
                    timeout=4,
                )
                if res.status_code == 200 and res.json().get("delivered"):
                    logger.info("Successfully delivered email via HTTPS mail relay to %s", to_email)
                    if settings.APP_ENV != "production":
                        try:
                            with self._outbox_path.open("a", encoding="utf-8") as fh:
                                fh.write(f"--- TO: {to_email} | SUBJECT: {subject} ---\n{text_body}\n\n")
                        except Exception:
                            pass
                    return {"delivered": True, "provider": "smtp"}
            except Exception as exc:
                logger.info("HTTPS mail relay skipped (%s), falling back to direct SMTP", exc)

        # 2. Secondary Priority: Direct SMTP (e.g. Gmail SMTP, SendGrid, custom mail servers)
        if self.is_smtp_configured():
            attempted_provider = "smtp"
            try:
                msg = EmailMessage()
                msg["Subject"] = subject
                from_addr = settings.SMTP_FROM_EMAIL or settings.SMTP_USER
                msg["From"] = f"TEAM OBSIDIAN <{from_addr}>"
                msg["To"] = to_email
                msg.set_content(text_body)
                msg.add_alternative(html_body, subtype="html")

                smtp_password = (settings.SMTP_PASSWORD or "").replace(" ", "").strip()
                if int(settings.SMTP_PORT) == 465:
                    with smtplib.SMTP_SSL(settings.SMTP_HOST, int(settings.SMTP_PORT), timeout=3) as server:
                        server.login(settings.SMTP_USER, smtp_password)
                        server.send_message(msg)
                else:
                    with smtplib.SMTP(settings.SMTP_HOST, int(settings.SMTP_PORT), timeout=3) as server:
                        server.ehlo()
                        server.starttls()
                        server.ehlo()
                        server.login(settings.SMTP_USER, smtp_password)
                        server.send_message(msg)
                if settings.APP_ENV != "production":
                    try:
                        with self._outbox_path.open("a", encoding="utf-8") as fh:
                            fh.write(f"--- TO: {to_email} | SUBJECT: {subject} ---\n{text_body}\n\n")
                    except Exception:
                        pass
                logger.info("Successfully delivered email via SMTP to %s", to_email)
                return {"delivered": True, "provider": "smtp"}
            except Exception as exc:
                error_code = "smtp_error"
                error_detail = str(exc)[:300]
                logger.warning("SMTP email delivery failed: %s", exc)

        # 3. Tertiary Fallback: Resend API (if configured)
        if settings.RESEND_API_KEY:
            attempted_provider = "resend"
            sender = (
                settings.SMTP_FROM_EMAIL.strip()
                if self.has_custom_sender_domain()
                else "TEAM OBSIDIAN <onboarding@resend.dev>"
            )
            try:
                res = requests.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": sender,
                        "to": [to_email],
                        "subject": subject,
                        "html": html_body,
                        "text": text_body,
                    },
                    timeout=4,
                )
                if 200 <= res.status_code < 300:
                    return {"delivered": True, "provider": "resend"}
                body_snippet = (res.text or "").strip()[:300]
                if res.status_code == 403 and (
                    "only send testing emails" in body_snippet.lower()
                    or "verify a domain" in body_snippet.lower()
                ):
                    error_code = "resend_sandbox_restricted"
                else:
                    error_code = f"resend_http_{res.status_code}"
                error_detail = body_snippet
                logger.warning("Resend email delivery failed (%s): %s", res.status_code, body_snippet)
            except Exception as exc:
                error_code = "resend_exception"
                error_detail = str(exc)[:300]
                logger.warning("Resend email exception: %s", exc)

        # 3. Development local outbox fallback
        if settings.APP_ENV != "production":
            try:
                with self._outbox_path.open("a", encoding="utf-8") as fh:
                    fh.write(f"--- TO: {to_email} | SUBJECT: {subject} ---\n{text_body}\n\n")
            except Exception:
                pass
            logger.info("Recorded email in dev outbox for %s (%s)", to_email, subject)
            return {
                "delivered": False,
                "provider": "dev_outbox",
                "attempted_provider": attempted_provider,
                "error_code": error_code,
                "error_detail": error_detail,
            }

        return {
            "delivered": False,
            "provider": attempted_provider or "unconfigured",
            "attempted_provider": attempted_provider,
            "error_code": error_code or "unconfigured",
            "error_detail": error_detail or "No outbound email provider configured.",
        }

    def send_otp_email(self, to_email: str, otp_code: str, user_name: Optional[str] = None) -> dict:
        """Deliver a high-security 6-digit OTP code with expiration and security warning."""
        greeting = f"Hi {user_name}," if user_name else "Hello,"
        escaped_user_name = html.escape(user_name, quote=True) if user_name else None
        html_greeting = f"Hi {escaped_user_name}," if escaped_user_name else "Hello,"

        text_body = (
            f"{greeting}\n\n"
            "We received a request to reset your TEAM OBSIDIAN account password.\n\n"
            f"Your 6-Digit Verification Code: {otp_code}\n"
            f"Reset code: {otp_code}\n\n"
            "SECURITY NOTICE:\n"
            "• This code is valid for 5 minutes only.\n"
            "• It can only be used once.\n"
            "• Maximum 5 verification attempts are allowed.\n"
            "• Never share this OTP with anyone, including TEAM OBSIDIAN staff.\n\n"
            "If you did not request a password reset, no changes have been made to your account. You can safely ignore this email.\n\n"
            "TEAM OBSIDIAN Security Team\n"
        )

        html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>TEAM OBSIDIAN Password Reset Verification</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0F172A; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #E2E8F0;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #0F172A; padding: 40px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 540px; background-color: #1E293B; border: 1px solid #334155; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4);">
          <!-- Header -->
          <tr>
            <td style="padding: 32px 32px 24px 32px; background: linear-gradient(135deg, #1E1238 0%, #0F172A 100%); border-bottom: 1px solid #334155;">
              <table role="presentation" width="100%">
                <tr>
                  <td>
                    <span style="font-size: 11px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; color: #A78BFA; background-color: rgba(167, 139, 250, 0.12); padding: 4px 10px; border-radius: 9999px; border: 1px solid rgba(167, 139, 250, 0.25);">TEAM OBSIDIAN</span>
                    <h1 style="margin: 14px 0 4px 0; font-size: 22px; font-weight: 700; color: #FFFFFF; letter-spacing: -0.5px;">Password Reset Verification</h1>
                    <p style="margin: 0; font-size: 12px; color: #94A3B8;">Autonomous Engineering Knowledge &amp; Handover Platform</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          
          <!-- Content Body -->
          <tr>
            <td style="padding: 32px;">
              <p style="margin: 0 0 16px 0; font-size: 14px; line-height: 1.6; color: #CBD5E1;">{html_greeting}</p>
              <p style="margin: 0 0 24px 0; font-size: 14px; line-height: 1.6; color: #CBD5E1;">
                We received a request to reset the password for your account. Use the single-use verification code below to complete the reset:
              </p>
              
              <!-- OTP Box -->
              <div style="background-color: #0B0F19; border: 1.5px solid #7C3AED; border-radius: 14px; padding: 24px 16px; text-align: center; margin: 24px 0 28px 0;">
                <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: #94A3B8; margin-bottom: 8px;">Your Verification Code</div>
                <div style="font-family: 'SF Mono', Monaco, Consolas, 'Courier New', monospace; font-size: 38px; font-weight: 800; letter-spacing: 12px; color: #A78BFA; text-indent: 12px;">{otp_code}</div>
                <div style="font-size: 11px; color: #64748B; margin-top: 8px;">Expires in 5 minutes &bull; Single-use only</div>
              </div>

              <!-- Security Information -->
              <div style="background-color: rgba(239, 68, 68, 0.08); border-left: 3px solid #EF4444; border-radius: 6px; padding: 12px 14px; margin-bottom: 24px;">
                <p style="margin: 0; font-size: 12px; line-height: 1.5; color: #FCA5A5;">
                  <strong>Security Reminder:</strong> Never share this code with anyone. TEAM OBSIDIAN engineers or support will never ask you for your verification code.
                </p>
              </div>

              <p style="margin: 0; font-size: 12px; line-height: 1.6; color: #64748B;">
                If you did not request a password reset, no changes were made to your account. You can safely ignore this email.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding: 20px 32px; background-color: #0B0F19; border-top: 1px solid #334155; text-align: center;">
              <p style="margin: 0; font-size: 11px; color: #475569;">
                &copy; TEAM OBSIDIAN &bull; Continuous Knowledge Reconstruction &amp; Engineering Continuity Engine
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

        return self.send_email(
            to_email=to_email,
            subject="TEAM OBSIDIAN — Password Reset Code: " + otp_code,
            html_body=html_body,
            text_body=text_body,
        )

    def send_password_reset_email(self, to_email: str, reset_token: str, user_name: Optional[str] = None) -> dict:
        query = urlencode({"token": reset_token, "email": to_email})
        reset_link = f"{settings.FRONTEND_URL}/forgot-password?{query}"
        greeting = f"Hi {user_name}," if user_name else "Hello,"
        escaped_user_name = html.escape(user_name, quote=True) if user_name else None
        html_greeting = f"Hi {escaped_user_name}," if escaped_user_name else "Hello,"
        text_body = (
            f"{greeting}\n\n"
            "We received a request to reset your TEAM OBSIDIAN password.\n"
            f"Reset link (expires in {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes, single-use):\n"
            f"{reset_link}\n\n"
            f"Reset code: {reset_token}\n\n"
            "If you did not request this, you can safely ignore this email."
        )
        html_body = (
            f"<p>{html_greeting}</p>"
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
        esc_reviewer = html.escape(str(reviewer_name or ""), quote=True)
        esc_title = html.escape(str(handover_title or ""), quote=True)
        esc_project = html.escape(str(project_name or ""), quote=True)
        esc_role = html.escape(str(role or ""), quote=True)
        html_body = (
            f"<p>Hi {esc_reviewer},</p>"
            f"<p>You have been requested to review and sign off on handover dossier "
            f"<strong>{esc_title}</strong> for project <strong>{esc_project}</strong> as <em>{esc_role}</em>.</p>"
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
        esc_recipient = html.escape(str(recipient_name or ""), quote=True)
        esc_project = html.escape(str(project_name or ""), quote=True)
        esc_target = html.escape(str(target_title or ""), quote=True)
        esc_drift = html.escape(str(drift_summary or ""), quote=True)
        esc_severity = html.escape(str(severity or "high"), quote=True)
        html_body = (
            f"<p>Hi {esc_recipient},</p>"
            f"<p><strong>[{esc_severity.upper()} KNOWLEDGE DRIFT]</strong> Detected in project <strong>{esc_project}</strong>:</p>"
            f"<p><strong>Target:</strong> {esc_target}<br/><strong>Details:</strong> {esc_drift}</p>"
            f"<p><a href=\"{evidence_url}\">Inspect Drift in Evidence Center</a></p>"
        )
        return self.send_email(
            to_email=to_email,
            subject=f"TEAM OBSIDIAN — Knowledge Drift Alert ({severity.upper()}): {project_name}",
            html_body=html_body,
            text_body=text_body,
        )


email_service = EmailService()
