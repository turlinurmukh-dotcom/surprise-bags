"""In-app merchant dashboard operations. These mirror the existing bot
commands (/post_listing, /set_photo, /set_description, /pickup) exactly —
same validation, same DB writes — just callable from the Mini App's API
instead of typed as chat commands. The bot commands keep working
unchanged; this is an additional interface on top of them, not a
replacement.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import LISTING_CATEGORIES, MERCHANT_DESCRIPTION_MAX_LEN, Listing, Merchant, Order
from app.services.orders import expire_overdue_orders


class DashboardError(Exception):
    """Raised when a dashboard action is invalid — mirrors the bot
    handlers' own validation messages so the experience is consistent
    across chat and in-app.
    """


def get_merchant_for_telegram_id(session: Session, telegram_id: int) -> Optional[Merchant]:
    return session.query(Merchant).filter_by(telegram_id=telegram_id).first()


def create_listing(
    session: Session,
    merchant: Merchant,
    category: str,
    original_price: int,
    discounted_price: int,
    quantity: int,
    pickup_start: datetime,
    pickup_end: datetime,
) -> Listing:
    if category not in LISTING_CATEGORIES:
        raise DashboardError(f"Invalid category. Choose one of: {', '.join(LISTING_CATEGORIES)}.")
    if original_price <= 0 or discounted_price <= 0:
        raise DashboardError("Prices must be positive.")
    if discounted_price >= original_price:
        raise DashboardError("Discounted price should be lower than the original price.")
    if quantity <= 0:
        raise DashboardError("Quantity must be a positive whole number.")
    if pickup_end <= pickup_start:
        raise DashboardError("Pickup end time must be after the start time.")

    listing = Listing(
        merchant_id=merchant.id,
        category=category,
        original_price=original_price,
        discounted_price=discounted_price,
        quantity_total=quantity,
        quantity_remaining=quantity,
        pickup_window_start=pickup_start,
        pickup_window_end=pickup_end,
        status="active",
    )
    session.add(listing)
    session.commit()
    session.refresh(listing)
    return listing


def cancel_listing(session: Session, merchant: Merchant, listing_id: int) -> Listing:
    """Merchant-scoped cancel — a merchant may only cancel their own
    listing, mirroring how /pickup is scoped to the caller's own listings.
    """
    listing = session.query(Listing).filter_by(id=listing_id, merchant_id=merchant.id).first()
    if listing is None:
        raise DashboardError("Listing not found.")
    if listing.status != "active":
        raise DashboardError("Listing is not active.")

    listing.status = "cancelled"
    session.commit()
    session.refresh(listing)
    return listing


def merchant_listings(session: Session, merchant: Merchant, limit: int = 20) -> list[Listing]:
    return (
        session.query(Listing)
        .filter_by(merchant_id=merchant.id)
        .order_by(Listing.created_at.desc())
        .limit(limit)
        .all()
    )


def pending_pickups(session: Session, merchant: Merchant) -> list[Order]:
    """This merchant's currently-reserved orders — the tap-to-confirm list.
    Runs the same overdue-expiry sweep confirm_pickup() does, so an order
    that just expired won't show as still pending.
    """
    expire_overdue_orders(session)
    return (
        session.query(Order)
        .join(Listing, Order.listing_id == Listing.id)
        .filter(Listing.merchant_id == merchant.id, Order.status == "reserved")
        .order_by(Order.created_at)
        .all()
    )


def set_photo(session: Session, merchant: Merchant, file_id: str) -> Merchant:
    db_merchant = session.query(Merchant).filter_by(id=merchant.id).first()
    db_merchant.photo_file_id = file_id
    session.commit()
    session.refresh(db_merchant)
    return db_merchant


def set_description(session: Session, merchant: Merchant, description: str) -> Merchant:
    description = description.strip()
    if not description:
        raise DashboardError("Description cannot be empty.")
    if len(description) > MERCHANT_DESCRIPTION_MAX_LEN:
        raise DashboardError(
            f"Description must be under {MERCHANT_DESCRIPTION_MAX_LEN} characters."
        )

    db_merchant = session.query(Merchant).filter_by(id=merchant.id).first()
    db_merchant.description = description
    session.commit()
    session.refresh(db_merchant)
    return db_merchant
