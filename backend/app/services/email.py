import logging
import secrets
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("tg.email")

_SUBJECTS = {
    "register": "Код подтверждения регистрации — TG Platform",
    "reset": "Код восстановления пароля — TG Platform",
}


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def send_code(email: str, code: str, purpose: str) -> None:
    """Send a one-time code. Falls back to logging when SMTP is not configured (dev)."""
    subject = _SUBJECTS.get(purpose, "Код подтверждения — TG Platform")
    body = f"Ваш код: {code}\n\nКод действует {settings.email_code_ttl_minutes} минут."

    if not settings.smtp_host:
        logger.warning("[DEV] email code for %s (%s): %s", email, purpose, code)
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = email
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)
