"""Fan-out helper: sends the same alert to every configured channel
(Discord/Telegram/Email). Channels without credentials are silently skipped,
so the pipeline never fails just because alerts aren't configured yet.
"""
from __future__ import annotations

from src.alerts.discord import send_discord_alert
from src.alerts.email_alert import send_email_alert
from src.alerts.telegram import send_telegram_alert


def broadcast_alert(subject: str, message: str) -> dict[str, bool]:
    return {
        "discord": send_discord_alert(f"**{subject}**\n{message}"),
        "telegram": send_telegram_alert(f"{subject}\n{message}"),
        "email": send_email_alert(subject, message),
    }
