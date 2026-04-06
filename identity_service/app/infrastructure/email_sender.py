"""Send emails via SMTP (verification link, forgot-password OTP)."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..core.config import settings

logger = logging.getLogger(__name__)


def _smtp_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)


def send_verification_email(to_email: str, verification_link: str) -> None:
    """Send email with verification link. No-op if SMTP not configured."""
    if not _smtp_configured():
        logger.warning("SMTP not configured; skipping verification email to %s", to_email)
        return

    subject = "Verify your email — ASTU Connect"
    body_text = f"""Hello,

Please verify your email address to complete your registration with ASTU Connect:

{verification_link}

This verification link will expire in {settings.VERIFICATION_TOKEN_EXPIRE_HOURS} hours.

If you did not request this, you can safely ignore this email.

Best regards,
The {settings.SMTP_FROM_NAME} Team
"""

    body_html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <p>Hello,</p>
        <p>Please verify your email address to complete your registration with ASTU Connect.</p>
        <p>
            <a href="{verification_link}" style="display: inline-block; padding: 10px 20px; font-size: 16px; color: #fff; background-color: #4CAF50; text-decoration: none; border-radius: 5px;">Verify Email</a>
        </p>
        <p>If the button doesn't work, <a href="{verification_link}" style="color: #4CAF50; text-decoration: underline;">click here</a>.</p>
        <p>This verification link will expire in {settings.VERIFICATION_TOKEN_EXPIRE_HOURS} hours.</p>
        <p>If you did not request this, you can safely ignore this email.</p>
        <p>Best regards,<br>The {settings.SMTP_FROM_NAME} Team</p>
      </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    
    # Attach plain text first, then HTML (email clients prefer the last attached part they can render)
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM_EMAIL, to_email, msg.as_string())
        logger.info("Verification email sent to %s", to_email)
    except Exception as e:
        logger.exception("Failed to send verification email to %s: %s", to_email, e)
        raise


def send_otp_email(to_email: str, otp: str) -> None:
    """Send email with OTP for password reset. No-op if SMTP not configured."""
    if not _smtp_configured():
        logger.warning("SMTP not configured; skipping OTP email to %s", to_email)
        return

    subject = "Your password reset code — ASTU Connect"
    body = f"""Hello,

Your password reset code is: {otp}

This code expires in {settings.OTP_EXPIRE_MINUTES} minutes.

If you did not request a password reset, you can ignore this email.

— {settings.SMTP_FROM_NAME}
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM_EMAIL, to_email, msg.as_string())
        logger.info("OTP email sent to %s", to_email)
    except Exception as e:
        logger.exception("Failed to send OTP email to %s: %s", to_email, e)
        raise
