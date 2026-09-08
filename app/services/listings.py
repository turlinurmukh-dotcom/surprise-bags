from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import CATEGORY_LABELS, Listing, Order, User
from app.services.notify import send_message
from app.services.orders import ReservationBlockedError, check_can_reserve, expire_overdue_orders
from app.timezone import format_almaty


class ReservationError(Exception):
    """Raised when a listing can't be reserved (sold out, expired, gone,
    over the active-reservation cap, or blocked for repeat no-shows).
    """


def get_or_create_user(session: Session, telegram_id: int, username: Optional[str]) -> User:
    user = session.query(User).filter_by(telegram_id=telegram_id).first()
    if user is None:
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


def active_listings(session: Session) -> list[Listing]:
    expire_overdue_orders(session)
    now = datetime.now(timezone.utc)
    return (
        session.query(Listing)
        .filter(
            Listing.status == "active",
            Listing.quantity_remaining > 0,
            Listing.pickup_window_end >= now,
        )
        .order_by(Listing.pickup_window_start)
        .all()
    )


def active_listings_for_merchant(session: Session, merchant_id: int) -> list[Listing]:
    """A single merchant's active listings, for the merchant detail screen.
    Same active-listing rules as active_listings(), just scoped to one
    merchant instead of returning the whole feed.
    """
    expire_overdue_orders(session)
    now = datetime.now(timezone.utc)
    return (
        session.query(Listing)
        .filter(
            Listing.merchant_id == merchant_id,
            Listing.status == "active",
            Listing.quantity_remaining > 0,
            Listing.pickup_window_end >= now,
        )
        .order_by(Listing.pickup_window_start)
        .all()
    )


def active_merchants(session: Session) -> list[dict]:
    """Consumer-facing merchant list: one row per merchant with at least
    one active listing, grouped from active_listings() rather than a
    separate query. pickup_window_start shown is the EARLIEST across that
    merchant's active listings — the most actionable single data point
    ("what can I get soonest here"), not a start-end range, since a range
    describes overall availability but doesn't tell the user whether to
    go now or come back later. Also used to sort the list soonest-first.
    """
    listings = active_listings(session)

    merchants: dict[int, dict] = {}
    for listing in listings:
        merchant = listing.merchant
        entry = merchants.get(merchant.id)
        if entry is None:
            merchants[merchant.id] = {
                "id": merchant.id,
                "name": merchant.name,
                "location_text": merchant.location_text,
                "photo_file_id": merchant.photo_file_id,
                "description": merchant.description,
                "latitude": merchant.latitude,
                "longitude": merchant.longitude,
                "earliest_pickup_start": listing.pickup_window_start,
                "bag_count": 1,
            }
        else:
            entry["bag_count"] += 1
            if listing.pickup_window_start < entry["earliest_pickup_start"]:
                entry["earliest_pickup_start"] = listing.pickup_window_start

    return sorted(merchants.values(), key=lambda m: m["earliest_pickup_start"])


def listing_to_card(listing: Listing) -> dict:
    """Consumer-facing view of a listing. Deliberately excludes any field
    that could reveal the bag's specific contents — category label and
    merchant storefront photo only, per the surprise-bag design constraint.
    """
    return {
        "id": listing.id,
        "merchant_id": listing.merchant_id,
        "merchant_name": listing.merchant.name,
        "location_text": listing.merchant.location_text,
        "merchant_photo_file_id": listing.merchant.photo_file_id,
        "merchant_description": listing.merchant.description,
        "latitude": listing.merchant.latitude,
        "longitude": listing.merchant.longitude,
        "category": listing.category,
        "category_label": CATEGORY_LABELS[listing.category],
        "original_price": listing.original_price,
        "discounted_price": listing.discounted_price,
        "quantity_remaining": listing.quantity_remaining,
        "pickup_window_start": listing.pickup_window_start,
        "pickup_window_end": listing.pickup_window_end,
    }


def reserve_listing(session: Session, listing_id: int, user: User) -> Order:
    """Reserve one bag from a listing. Raises ReservationError if unavailable,
    over the per-user active-reservation cap, or blocked for repeat no-shows.

    Caller owns the session/transaction boundary (commits on success).
    Note: not safe against concurrent reservations racing on the same
    listing under SQLite — acceptable for a trial, revisit before real load.
    """
    expire_overdue_orders(session)

    try:
        check_can_reserve(session, user)
    except ReservationBlockedError as exc:
        raise ReservationError(str(exc)) from exc

    listing = session.query(Listing).filter_by(id=listing_id).first()
    if listing is None or listing.status != "active" or listing.quantity_remaining <= 0:
        raise ReservationError("This listing is no longer available.")

    listing.quantity_remaining -= 1
    if listing.quantity_remaining == 0:
        listing.status = "sold_out"

    order = Order(
        listing_id=listing.id,
        user_id=user.id,
        status="reserved",
        payment_status="pending",
        pickup_code=secrets.token_hex(3).upper(),
    )
    session.add(order)
    session.commit()
    session.refresh(order)

    send_message(
        listing.merchant.telegram_id,
        f"New reservation for listing #{listing.id} ({CATEGORY_LABELS[listing.category]}): "
        f"code {order.pickup_code}, pickup {format_almaty(listing.pickup_window_start)}"
        f"–{format_almaty(listing.pickup_window_end)}. "
        f"Confirm with /pickup {order.pickup_code} when they arrive.",
    )

    return order
