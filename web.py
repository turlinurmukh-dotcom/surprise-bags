from __future__ import annotations

import json
import logging
import os
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from urllib.error import HTTPError, URLError

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.bot_setup import build_bot_and_dispatcher
from app.db.models import CATEGORY_LABELS, Merchant, Order
from app.db.session import get_session
from app.services.listings import (
    ReservationError,
    active_listings,
    active_listings_for_merchant,
    active_merchants,
    get_or_create_user,
    listing_to_card,
    reserve_listing,
)
from app.services.merchant_dashboard import (
    DashboardError,
    cancel_listing,
    create_listing,
    get_merchant_for_telegram_id,
    merchant_listings,
    pending_pickups,
    set_description,
    set_photo,
)
from app.services.notify import PhotoUploadError, upload_photo_get_file_id
from app.services.orders import PickupConfirmError, confirm_pickup, user_orders
from app.services.reports import merchant_daily_stats
from app.services.reviews import (
    ReviewError,
    merchant_rating_breakdown,
    merchant_ratings_bulk,
    submit_review,
)
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


app = FastAPI(title="Sarqyt Mini App", lifespan=lifespan)


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


def _authenticate_merchant(session, x_telegram_init_data: str) -> Merchant:
    """Every dashboard endpoint calls this independently — /api/merchant/me
    is only for deciding whether to show the Dashboard nav entry in the UI;
    it is never the trust boundary itself. Each action re-verifies the
    caller against Merchant.telegram_id here, exactly like the bot
    handlers do via get_merchant_by_telegram_id.
    """
    tg_user = _authenticate(x_telegram_init_data)
    merchant = get_merchant_for_telegram_id(session, tg_user["id"])
    if merchant is None:
        raise HTTPException(status_code=403, detail="Not registered as a merchant")
    return merchant


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
        listings = active_listings(session)
        cards = [listing_to_card(listing) for listing in listings]
        ratings = merchant_ratings_bulk(session, [c["merchant_id"] for c in cards])
        for card in cards:
            rating = ratings.get(card["merchant_id"])
            card["merchant_rating"] = rating["average"] if rating else None
            card["merchant_rating_count"] = rating["count"] if rating else 0
        return [_serialize_card(card) for card in cards]
    finally:
        session.close()


def _serialize_merchant_summary(merchant: dict) -> dict:
    return {
        **merchant,
        "earliest_pickup_start": merchant["earliest_pickup_start"].isoformat(),
    }


@app.get("/api/merchants")
def get_merchants() -> list[dict]:
    """Consumer-facing merchant list — the new default Browse view. One row
    per merchant with at least one active listing, sorted by soonest pickup.
    """
    session = get_session()
    try:
        merchants = active_merchants(session)
        ratings = merchant_ratings_bulk(session, [m["id"] for m in merchants])
        for merchant in merchants:
            rating = ratings.get(merchant["id"])
            merchant["rating"] = rating["average"] if rating else None
            merchant["rating_count"] = rating["count"] if rating else 0
        return [_serialize_merchant_summary(m) for m in merchants]
    finally:
        session.close()


@app.get("/api/merchants/{merchant_id}")
def get_merchant_detail(merchant_id: int) -> dict:
    """Merchant detail screen: profile fields + this merchant's active bags,
    using the same listing_to_card() shape as the old flat feed so the
    Mini App can reuse its existing bag-card component unchanged.
    """
    session = get_session()
    try:
        merchant = session.get(Merchant, merchant_id)
        if merchant is None:
            raise HTTPException(status_code=404, detail="Merchant not found")

        listings = active_listings_for_merchant(session, merchant_id)
        cards = [_serialize_card(listing_to_card(listing)) for listing in listings]
        breakdown = merchant_rating_breakdown(session, merchant_id)

        return {
            "id": merchant.id,
            "name": merchant.name,
            "location_text": merchant.location_text,
            "photo_file_id": merchant.photo_file_id,
            "description": merchant.description,
            "latitude": merchant.latitude,
            "longitude": merchant.longitude,
            "rating": breakdown["overall"],
            "rating_count": breakdown["count"],
            "rating_quality": breakdown["quality"],
            "rating_quantity": breakdown["quantity"],
            "rating_variety": breakdown["variety"],
            "listings": cards,
        }
    finally:
        session.close()


def _serialize_listing_summary(listing) -> dict:
    return {
        "id": listing.id,
        "status": listing.status,
        "category": listing.category,
        "category_label": CATEGORY_LABELS[listing.category],
        "original_price": listing.original_price,
        "discounted_price": listing.discounted_price,
        "quantity_total": listing.quantity_total,
        "quantity_remaining": listing.quantity_remaining,
        "pickup_window_start": listing.pickup_window_start.isoformat(),
        "pickup_window_end": listing.pickup_window_end.isoformat(),
        "created_at": listing.created_at.isoformat(),
    }


@app.get("/api/merchant/me")
def get_merchant_me(x_telegram_init_data: str = Header(default="")) -> dict:
    """UI-visibility check only — decides whether to show the Dashboard nav
    entry. Not a trust boundary: every dashboard endpoint below re-verifies
    the caller independently via _authenticate_merchant.
    """
    tg_user = _authenticate(x_telegram_init_data)
    session = get_session()
    try:
        merchant = get_merchant_for_telegram_id(session, tg_user["id"])
        if merchant is None:
            raise HTTPException(status_code=404, detail="Not registered as a merchant")
        return {
            "id": merchant.id,
            "name": merchant.name,
            "location_text": merchant.location_text,
            "photo_file_id": merchant.photo_file_id,
            "description": merchant.description,
        }
    finally:
        session.close()


@app.get("/api/merchant/listings")
def get_merchant_listings(x_telegram_init_data: str = Header(default="")) -> list[dict]:
    session = get_session()
    try:
        merchant = _authenticate_merchant(session, x_telegram_init_data)
        listings = merchant_listings(session, merchant)
        return [_serialize_listing_summary(listing) for listing in listings]
    finally:
        session.close()


class CreateListingRequest(BaseModel):
    category: str
    original_price: int
    discounted_price: int
    quantity: int
    pickup_window_start: str
    pickup_window_end: str


@app.post("/api/merchant/listings")
def post_merchant_listing(
    body: CreateListingRequest, x_telegram_init_data: str = Header(default="")
) -> dict:
    session = get_session()
    try:
        merchant = _authenticate_merchant(session, x_telegram_init_data)
        try:
            pickup_start = datetime.fromisoformat(body.pickup_window_start)
            pickup_end = datetime.fromisoformat(body.pickup_window_end)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pickup time format") from exc

        try:
            listing = create_listing(
                session,
                merchant,
                body.category,
                body.original_price,
                body.discounted_price,
                body.quantity,
                pickup_start,
                pickup_end,
            )
        except DashboardError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _serialize_listing_summary(listing)
    finally:
        session.close()


@app.post("/api/merchant/listings/{listing_id}/cancel")
def post_cancel_listing(listing_id: int, x_telegram_init_data: str = Header(default="")) -> dict:
    session = get_session()
    try:
        merchant = _authenticate_merchant(session, x_telegram_init_data)
        try:
            listing = cancel_listing(session, merchant, listing_id)
        except DashboardError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _serialize_listing_summary(listing)
    finally:
        session.close()


@app.get("/api/merchant/pending-pickups")
def get_pending_pickups(x_telegram_init_data: str = Header(default="")) -> list[dict]:
    session = get_session()
    try:
        merchant = _authenticate_merchant(session, x_telegram_init_data)
        orders = pending_pickups(session, merchant)
        return [
            {
                "id": order.id,
                "pickup_code": order.pickup_code,
                "category_label": CATEGORY_LABELS[order.listing.category],
                "pickup_window_start": order.listing.pickup_window_start.isoformat(),
                "pickup_window_end": order.listing.pickup_window_end.isoformat(),
                "created_at": order.created_at.isoformat(),
            }
            for order in orders
        ]
    finally:
        session.close()


@app.post("/api/merchant/pending-pickups/{order_id}/confirm")
def post_confirm_pickup(order_id: int, x_telegram_init_data: str = Header(default="")) -> dict:
    session = get_session()
    try:
        merchant = _authenticate_merchant(session, x_telegram_init_data)
        order = session.get(Order, order_id)
        if order is None or order.listing.merchant_id != merchant.id:
            raise HTTPException(status_code=404, detail="Order not found")
        try:
            confirmed = confirm_pickup(session, merchant, order.pickup_code)
        except PickupConfirmError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": confirmed.id, "status": confirmed.status}
    finally:
        session.close()


@app.get("/api/merchant/stats")
def get_merchant_stats(x_telegram_init_data: str = Header(default="")) -> dict:
    session = get_session()
    try:
        merchant = _authenticate_merchant(session, x_telegram_init_data)
        return merchant_daily_stats(session, merchant)
    finally:
        session.close()


class SetDescriptionRequest(BaseModel):
    description: str


@app.post("/api/merchant/description")
def post_merchant_description(
    body: SetDescriptionRequest, x_telegram_init_data: str = Header(default="")
) -> dict:
    session = get_session()
    try:
        merchant = _authenticate_merchant(session, x_telegram_init_data)
        try:
            updated = set_description(session, merchant, body.description)
        except DashboardError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"description": updated.description}
    finally:
        session.close()


MAX_PHOTO_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB — generous for a phone photo, small enough to reject junk fast

# Recognize real image files by their leading bytes rather than trusting
# the browser-supplied Content-Type, which is trivial to spoof or simply
# wrong (e.g. a renamed .txt file uploaded as "image/jpeg").
_IMAGE_MAGIC_BYTES = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"RIFF", "webp"),  # WEBP also starts with RIFF....WEBP; good enough here
)


def _sniff_image_type(data: bytes) -> Optional[str]:
    for magic, kind in _IMAGE_MAGIC_BYTES:
        if data.startswith(magic):
            return kind
    return None


@app.post("/api/merchant/photo")
async def post_merchant_photo(
    photo: UploadFile, x_telegram_init_data: str = Header(default="")
) -> dict:
    session = get_session()
    try:
        merchant = _authenticate_merchant(session, x_telegram_init_data)

        data = await photo.read(MAX_PHOTO_UPLOAD_BYTES + 1)
        if len(data) > MAX_PHOTO_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Photo must be under {MAX_PHOTO_UPLOAD_BYTES // (1024 * 1024)} MB.",
            )
        if not data:
            raise HTTPException(status_code=400, detail="No photo data received.")
        if _sniff_image_type(data) is None:
            raise HTTPException(
                status_code=400,
                detail="That doesn't look like a valid image file (jpeg/png/gif/webp).",
            )

        try:
            file_id = upload_photo_get_file_id(merchant.telegram_id, data)
        except PhotoUploadError as exc:
            logger.warning("photo upload failed for merchant_id=%s: %s", merchant.id, exc)
            raise HTTPException(
                status_code=502, detail="Couldn't upload the photo. Try again."
            ) from exc

        # Only reaches here — and only touches the stored photo_file_id —
        # once the upload has actually succeeded end-to-end. Any failure
        # above leaves the merchant's existing photo untouched.
        updated = set_photo(session, merchant, file_id)
        return {"photo_file_id": updated.photo_file_id}
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


class ReviewRequest(BaseModel):
    quality_rating: int = Field(ge=1, le=5)
    quantity_rating: int = Field(ge=1, le=5)
    variety_rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None


@app.post("/api/orders/{order_id}/review")
def post_review(
    order_id: int, body: ReviewRequest, x_telegram_init_data: str = Header(default="")
) -> dict:
    tg_user = _authenticate(x_telegram_init_data)

    session = get_session()
    try:
        user = get_or_create_user(session, tg_user["id"], tg_user.get("username"))
        try:
            review = submit_review(
                session,
                user,
                order_id,
                body.quality_rating,
                body.quantity_rating,
                body.variety_rating,
                body.comment,
            )
        except ReviewError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        overall = round(
            (review.quality_rating + review.quantity_rating + review.variety_rating) / 3.0, 1
        )
        return {
            "id": review.id,
            "quality_rating": review.quality_rating,
            "quantity_rating": review.quantity_rating,
            "variety_rating": review.variety_rating,
            "overall": overall,
            "comment": review.comment,
        }
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
