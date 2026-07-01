from __future__ import annotations

import logging

import requests

from src.config import settings

logger = logging.getLogger(__name__)


def send_discord_alert(message: str) -> bool:
    if not settings.discord_webhook_url:
        return False
    try:
        resp = requests.post(settings.discord_webhook_url, json={"content": message}, timeout=10)
        return resp.ok
    except Exception as exc:
        logger.warning("Discord alert failed: %s", exc)
        return False
