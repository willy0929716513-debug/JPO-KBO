from __future__ import annotations

import logging

import requests

from src.config import settings

logger = logging.getLogger(__name__)


def send_telegram_alert(message: str) -> bool:
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": settings.telegram_chat_id, "text": message}, timeout=10)
        return resp.ok
    except Exception as exc:
        logger.warning("Telegram alert failed: %s", exc)
        return False
