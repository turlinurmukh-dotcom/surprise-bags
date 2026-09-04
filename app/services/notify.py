"""Sends Telegram DMs from either process (bot or web) via a plain HTTP
call to the Bot API, rather than requiring an aiogram Bot instance —
the FastAPI process has no running bot/dispatcher of its own.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)


def send_message(telegram_id: int, text: str) -> bool:
    """Best-effort notification. Returns False (and logs) on failure rather
    than raising — a failed DM must never block the reservation/pickup/
    expiry flow that triggered it (e.g. user blocked the bot).
    """
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.warning("cannot send notification: BOT_TOKEN not set")
        return False

    payload = json.dumps({"chat_id": telegram_id, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return True
    except (HTTPError, URLError) as exc:
        logger.warning("failed to notify telegram_id=%s: %s", telegram_id, exc)
        return False
