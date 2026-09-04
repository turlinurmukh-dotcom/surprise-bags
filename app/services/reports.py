"""Reporting built directly on Listing/Order — no separate revenue
tracking. Orders are the source of truth; these are just aggregate
queries over them.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import Listing, Merchant, Order
from app.services.orders import expire_overdue_orders
from app.timezone import ALMATY_TZ

# Placeholder until real merchant terms are set — see task that introduced
# this. Keep this the single place the rate is defined.
PLATFORM_COMMISSION_RATE = 0.20


def _almaty_day_bounds(reference: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """UTC [start, end) bounds for "today" as defined in Almaty local time —
    matches how merchants/consumers actually think about a day, not UTC's.
    """
    reference = reference or datetime.now(timezone.utc)
    local_now = reference.astimezone(ALMATY_TZ)
    local_midnight = datetime.combine(local_now.date(), time.min, tzinfo=ALMATY_TZ)
    start = local_midnight.astimezone(timezone.utc)
    end = (local_midnight + timedelta(days=1)).astimezone(timezone.utc)
    return start, end


def merchant_daily_stats(session: Session, merchant: Merchant) -> dict:
    """Today's activity for one merchant: posted, sold, remaining, no-shows.
    "Today" is the current Almaty-local day, since that's what pickup
    windows are scheduled against.
    """
    expire_overdue_orders(session)
    day_start, day_end = _almaty_day_bounds()

    listings_today = (
        session.query(Listing)
        .filter(
            Listing.merchant_id == merchant.id,
            Listing.created_at >= day_start,
            Listing.created_at < day_end,
        )
        .all()
    )

    orders_today = (
        session.query(Order)
        .join(Listing, Order.listing_id == Listing.id)
        .filter(
            Listing.merchant_id == merchant.id,
            Order.created_at >= day_start,
            Order.created_at < day_end,
        )
        .all()
    )

    bags_posted = sum(listing.quantity_total for listing in listings_today)
    bags_remaining = sum(listing.quantity_remaining for listing in listings_today)
    bags_sold = sum(1 for order in orders_today if order.status == "picked_up")
    no_shows = sum(1 for order in orders_today if order.status == "no_show")

    return {
        "listings_posted": len(listings_today),
        "bags_posted": bags_posted,
        "bags_sold": bags_sold,
        "bags_remaining": bags_remaining,
        "no_shows": no_shows,
    }


WINDOWS = ("today", "week", "all_time")


def _window_bounds(window: str) -> tuple[Optional[datetime], Optional[datetime]]:
    if window == "today":
        return _almaty_day_bounds()
    if window == "week":
        day_start, _ = _almaty_day_bounds()
        return day_start - timedelta(days=7), None
    if window == "all_time":
        return None, None
    raise ValueError(f"Unknown window: {window!r}. Expected one of {WINDOWS}.")


def platform_summary(session: Session, window: str = "all_time") -> dict:
    """Platform-level totals over a selectable window. GMV and commission
    are derived from picked-up orders' discounted_price — the price that
    actually changed hands, not the listing's original price.
    """
    expire_overdue_orders(session)
    start, end = _window_bounds(window)

    query = session.query(Order).join(Listing, Order.listing_id == Listing.id)
    if start is not None:
        query = query.filter(Order.created_at >= start)
    if end is not None:
        query = query.filter(Order.created_at < end)
    orders = query.all()

    picked_up = [o for o in orders if o.status == "picked_up"]
    no_shows = [o for o in orders if o.status == "no_show"]
    completed = picked_up + no_shows  # excludes still-"reserved" — not yet resolved

    gmv = sum(order.listing.discounted_price for order in picked_up)
    commission = round(gmv * PLATFORM_COMMISSION_RATE)

    no_show_rate = (len(no_shows) / len(completed)) if completed else 0.0

    return {
        "window": window,
        "bags_sold": len(picked_up),
        "no_shows": len(no_shows),
        "total_reservations": len(orders),
        "gmv": gmv,
        "commission_rate": PLATFORM_COMMISSION_RATE,
        "commission_revenue": commission,
        "no_show_rate": no_show_rate,
    }
