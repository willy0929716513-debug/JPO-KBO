from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

from src.config import settings

logger = logging.getLogger(__name__)


def send_email_alert(subject: str, message: str) -> bool:
    if not (settings.smtp_host and settings.smtp_user and settings.smtp_password and settings.alert_email_to):
        return False
    try:
        msg = MIMEText(message)
        msg["Subject"] = subject
        msg["From"] = settings.smtp_user
        msg["To"] = settings.alert_email_to
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        return True
    except Exception as exc:
        logger.warning("Email alert failed: %s", exc)
        return False
