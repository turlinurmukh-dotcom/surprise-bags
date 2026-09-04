from __future__ import annotations

import json
import logging
import os
import urllib.request
from contextlib import asynccontextmanager
from urllib.error import HTTPError, URLError

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app.bot_setup import build_bot_and_dispatcher
from app.db.session import get_session
from app.services.listings import (
    ReservationError,
    active_listings,
    get_or_create_user,
    listing_to_card,
    reserve_listing,
)
from app.services.orders import user_orders
from app.webapp_auth import InitDataError, verify_init_data

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# USE_WEBHOOK gates whether this process also runs the bot. Local dev
# leaves it unset and runs the bot separately via `python main.py`
# (polling — no public URL needed). Render sets USE_WEBHOOK=1 so the
# bot lives inside this same process/service, since the free tier only
# gives us one.
USE_WEBHOOK = os.getenv("USE_WEBHOOK") == "1"
WEBHOOK_PATH = "/webhook/telegram"
webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")

bot = None
dp = None
if USE_WEBHOOK:
    bot, dp = build_bot_and_dispatcher()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if USE_WEBHOOK:
        webhook_url = os.getenv("WEBHOOK_URL")
        if not webhook_url:
            raise RuntimeError("USE_WEBHOOK=1 but WEBHOOK_URL is not set")
        await bot.set_webhook(
            url=f"{webhook_url.rstrip('/')}{WEBHOOK_PATH}",
            secret_token=webhook_secret,
            drop_pending_updates=False,
        )
        logger.info("Webhook set to %s%s", webhook_url, WEBHOOK_PATH)
    yield
    if USE_WEBHOOK:
        await bot.session.close()


app = FastAPI(title="Surprise Bags Mini App", lifespan=lifespan)


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request) -> dict:
    if not USE_WEBHOOK:
        raise HTTPException(status_code=404, detail="Webhook mode not enabled")

    if webhook_secret:
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if header != webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid secret token")

    update_data = await request.json()
    await dp.feed_webhook_update(bot, update_data)
    return {"ok": True}


def _authenticate(x_telegram_init_data: str = Header(default="")) -> dict:
    try:
        return verify_init_data(x_telegram_init_data)
    except InitDataError as exc:
        logger.warning("initData verification failed: %s", exc)
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _serialize_card(card: dict) -> dict:
    return {
        **card,
        "pickup_window_start": card["pickup_window_start"].isoformat(),
        "pickup_window_end": card["pickup_window_end"].isoformat(),
    }


@app.get("/api/config")
def get_config() -> dict:
    """Client-side config. The 2GIS key is a domain-restricted public key
    (like a Google Maps JS key), not a secret — fine to expose to the page.
    """
    return {"twogis_api_key": os.getenv("TWOGIS_API_KEY") or None}


@app.get("/api/listings")
def get_listings() -> list[dict]:
    session = get_session()
    try:
        return [_serialize_card(listing_to_card(listing)) for listing in active_listings(session)]
    finally:
        session.close()


@app.post("/api/listings/{listing_id}/reserve")
def post_reserve(listing_id: int, x_telegram_init_data: str = Header(default="")) -> dict:
    tg_user = _authenticate(x_telegram_init_data)

    session = get_session()
    try:
        user = get_or_create_user(session, tg_user["id"], tg_user.get("username"))
        try:
            order = reserve_listing(session, listing_id, user)
        except ReservationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "order_id": order.id,
            "pickup_code": order.pickup_code,
            "status": order.status,
            "payment_status": order.payment_status,
        }
    finally:
        session.close()


def _serialize_order(order: dict) -> dict:
    return {
        **order,
        "pickup_window_start": order["pickup_window_start"].isoformat(),
        "pickup_window_end": order["pickup_window_end"].isoformat(),
        "picked_up_at": order["picked_up_at"].isoformat() if order["picked_up_at"] else None,
        "created_at": order["created_at"].isoformat(),
    }


@app.get("/api/orders/me")
def get_my_orders(x_telegram_init_data: str = Header(default="")) -> list[dict]:
    tg_user = _authenticate(x_telegram_init_data)

    session = get_session()
    try:
        user = get_or_create_user(session, tg_user["id"], tg_user.get("username"))
        return [_serialize_order(order) for order in user_orders(session, user)]
    finally:
        session.close()


_FILE_ID_ALPHABET = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_="
)


@app.get("/api/photo/{file_id}")
def get_photo(file_id: str) -> Response:
    """Proxies a Telegram file (e.g. a merchant's storefront photo) so the
    bot token never reaches the browser — Telegram's file URLs embed it.
    """
    if not file_id or not set(file_id) <= _FILE_ID_ALPHABET:
        raise HTTPException(status_code=400, detail="Invalid file id")

    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise HTTPException(status_code=500, detail="Server misconfigured")

    try:
        with urllib.request.urlopen(
            f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}", timeout=10
        ) as resp:
            file_path = json.load(resp)["result"]["file_path"]

        with urllib.request.urlopen(
            f"https://api.telegram.org/file/bot{bot_token}/{file_path}", timeout=10
        ) as resp:
            content = resp.read()
            content_type = resp.headers.get("Content-Type", "image/jpeg")
    except (HTTPError, URLError, KeyError) as exc:
        logger.warning("failed to fetch photo file_id=%s: %s", file_id, exc)
        raise HTTPException(status_code=404, detail="Photo not found") from exc

    return Response(content=content, media_type=content_type)


app.mount("/", StaticFiles(directory="static", html=True), name="static")
