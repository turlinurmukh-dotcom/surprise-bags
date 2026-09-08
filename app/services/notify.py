"""Sends Telegram DMs from either process (bot or web) via a plain HTTP
call to the Bot API, rather than requiring an aiogram Bot instance —
the FastAPI process has no running bot/dispatcher of its own.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import uuid
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)


class PhotoUploadError(Exception):
    """Raised when uploading a photo to Telegram fails. Unlike
    send_message's best-effort/never-raise style, callers here are about
    to persist the resulting file_id — they need to know if it failed
    rather than silently doing nothing.
    """


def upload_photo_get_file_id(chat_id: int, image_bytes: bytes) -> str:
    """Sends image_bytes to chat_id via Telegram's sendPhoto and returns the
    resulting file_id. This is the only way to get a file_id for a photo
    from outside a Telegram client — the Mini App itself can't reach
    Telegram's file storage directly (no bot token client-side), so this
    is the piece of an in-app photo upload that always goes through the
    bot API on the server, not the browser.
    """
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise PhotoUploadError("Server misconfigured: BOT_TOKEN not set")

    boundary = uuid.uuid4().hex
    body = bytearray()

    def add_field(name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(f"{value}\r\n".encode())

    add_field("chat_id", str(chat_id))
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        b'Content-Disposition: form-data; name="photo"; filename="photo.jpg"\r\n'
    )
    body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
    body.extend(image_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendPhoto",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.load(resp)
    except HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise PhotoUploadError(f"Telegram upload failed: {exc} — {body}") from exc
    except URLError as exc:
        raise PhotoUploadError(f"Telegram upload failed: {exc}") from exc

    if not result.get("ok"):
        raise PhotoUploadError(f"Telegram rejected the photo: {result.get('description')}")

    try:
        sizes = result["result"]["photo"]
        return sizes[-1]["file_id"]
    except (KeyError, IndexError) as exc:
        raise PhotoUploadError("Unexpected response from Telegram") from exc


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
