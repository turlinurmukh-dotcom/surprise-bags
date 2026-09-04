"""Verification of Telegram Mini App `initData`.

Telegram signs initData with HMAC-SHA256 using a key derived from the bot
token. See: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Optional
from urllib.parse import parse_qsl

INIT_DATA_MAX_AGE_SECONDS = 24 * 60 * 60  # Telegram's own recommended staleness bound.


class InitDataError(Exception):
    pass


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def verify_init_data(init_data: str, bot_token: Optional[str] = None) -> dict:
    """Verify initData's HMAC signature and freshness. Returns the parsed
    user dict on success. Raises InitDataError on any failure — callers
    must treat that as an unauthenticated request, never a soft-fail.
    """
    bot_token = bot_token or os.getenv("BOT_TOKEN")
    if not bot_token:
        raise InitDataError("Server misconfigured: BOT_TOKEN not set")

    if not init_data:
        raise InitDataError("Missing initData")

    pairs = parse_qsl(init_data, strict_parsing=True)
    data = dict(pairs)

    received_hash = data.pop("hash", None)
    if not received_hash:
        raise InitDataError("initData missing hash")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = _secret_key(bot_token)
    computed_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise InitDataError("initData signature mismatch")

    auth_date = data.get("auth_date")
    if not auth_date or not auth_date.isdigit():
        raise InitDataError("initData missing/invalid auth_date")

    age = time.time() - int(auth_date)
    if age > INIT_DATA_MAX_AGE_SECONDS:
        raise InitDataError("initData is stale")

    user_raw = data.get("user")
    if not user_raw:
        raise InitDataError("initData missing user")

    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise InitDataError("initData user field is not valid JSON") from exc

    if "id" not in user:
        raise InitDataError("initData user missing id")

    return user
