from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import CATEGORY_LABELS, Listing, Merchant, Order, Review, User
from app.services.notify import send_message
from app.timezone import format_almaty

MAX_ACTIVE_RESERVATIONS = 2
NO_SHOW_THRESHOLD = 3
NO_SHOW_WINDOW_DAYS = 30
BLOCK_DURATION_DAYS = 7


class ReservationBlockedError(Exception):
    """User is over the active-reservation cap or under a no-show block."""


class PickupConfirmError(Exception):
    """Pickup code didn't match an active order for this merchant."""


def expire_overdue_orders(session: Session) -> int:
    """Check-on-read sweep: any 'reserved' order whose listing's pickup
    window has ended is a no-show. Marks it, returns the bag to stock,
    and bumps the user's no_show_count. Called at the top of every
    order/listing-touching service function so no cron job is needed.

    Returns the number of orders expired (0 in the common case).
    """
    now = datetime.now(timezone.utc)

    overdue = (
        session.query(Order)
        .join(Listing, Order.listing_id == Listing.id)
        .filter(Order.status == "reserved", Listing.pickup_window_end < now)
        .all()
    )

    for order in overdue:
        order.status = "no_show"
        order.expired_at = now

        listing = order.listing
        if listing.status == "sold_out":
            listing.status = "active"
        listing.quantity_remaining += 1

        order.user.no_show_count += 1

    if overdue:
        session.commit()
        for order in overdue:
            listing = order.listing
            send_message(
                listing.merchant.telegram_id,
                f"Listing #{listing.id} ({CATEGORY_LABELS[listing.category]}) had an "
                f"unclaimed bag — pickup code {order.pickup_code} expired at "
                f"{format_almaty(listing.pickup_window_end)} without being picked up. "
                "It's back in your available stock count.",
            )

    return len(overdue)


def _active_reservation_count(session: Session, user: User) -> int:
    return (
        session.query(Order)
        .filter(Order.user_id == user.id, Order.status == "reserved")
        .count()
    )


def _recent_no_show_count(session: Session, user: User) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=NO_SHOW_WINDOW_DAYS)
    return (
        session.query(Order)
        .filter(
            Order.user_id == user.id,
            Order.status == "no_show",
            Order.expired_at >= cutoff,
        )
        .count()
    )


def check_can_reserve(session: Session, user: User) -> None:
    """Raises ReservationBlockedError if the user can't reserve right now.
    Call after expire_overdue_orders() so the active count/no-show count
    reflect anything that just expired.
    """
    now = datetime.now(timezone.utc)

    if user.blocked_until and user.blocked_until > now:
        remaining_days = max(1, (user.blocked_until - now).days + 1)
        raise ReservationBlockedError(
            f"You've had {NO_SHOW_THRESHOLD}+ no-shows recently, so new reservations "
            f"are paused for {remaining_days} more day(s). Thanks for understanding — "
            "this keeps bags available for people who'll actually pick them up."
        )

    if user.blocked_until and user.blocked_until <= now:
        user.blocked_until = None
        session.commit()

    recent_no_shows = _recent_no_show_count(session, user)
    if recent_no_shows >= NO_SHOW_THRESHOLD:
        user.blocked_until = now + timedelta(days=BLOCK_DURATION_DAYS)
        session.commit()
        raise ReservationBlockedError(
            f"You've had {NO_SHOW_THRESHOLD}+ no-shows in the last {NO_SHOW_WINDOW_DAYS} days, "
            f"so new reservations are paused for {BLOCK_DURATION_DAYS} days."
        )

    active_count = _active_reservation_count(session, user)
    if active_count >= MAX_ACTIVE_RESERVATIONS:
        raise ReservationBlockedError(
            f"You already have {MAX_ACTIVE_RESERVATIONS} active reservations — "
            "pick one up (or let it expire) before reserving another."
        )


def confirm_pickup(session: Session, merchant: Merchant, pickup_code: str) -> Order:
    """Merchant confirms a code. Scoped to this merchant's own listings only —
    a merchant must never be able to confirm another merchant's order.
    """
    expire_overdue_orders(session)

    order = (
        session.query(Order)
        .join(Listing, Order.listing_id == Listing.id)
        .filter(
            Listing.merchant_id == merchant.id,
            Order.pickup_code == pickup_code.strip().upper(),
            Order.status == "reserved",
        )
        .first()
    )
    if order is None:
        raise PickupConfirmError(
            "No active reservation with that code for your listings. "
            "It may already be picked up, expired, or the code's wrong."
        )

    order.status = "picked_up"
    order.picked_up_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(order)

    send_message(
        order.user.telegram_id,
        f"Picked up! Thanks for rescuing a {CATEGORY_LABELS[order.listing.category]} "
        f"from {merchant.name} — one less bag going to waste. 🌱",
    )

    return order


def user_orders(session: Session, user: User) -> list[dict]:
    """Shared by the bot's /my_orders and the Mini App's profile screen."""
    expire_overdue_orders(session)

    orders = (
        session.query(Order)
        .filter(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
        .limit(20)
        .all()
    )

    order_ids = [order.id for order in orders]
    reviewed_order_ids = set()
    if order_ids:
        reviewed_order_ids = {
            row[0]
            for row in session.query(Review.order_id).filter(Review.order_id.in_(order_ids)).all()
        }

    return [
        {
            "id": order.id,
            "status": order.status,
            "payment_status": order.payment_status,
            "pickup_code": order.pickup_code,
            "category": order.listing.category,
            "category_label": CATEGORY_LABELS[order.listing.category],
            "merchant_name": order.listing.merchant.name,
            "location_text": order.listing.merchant.location_text,
            "discounted_price": order.listing.discounted_price,
            "pickup_window_start": order.listing.pickup_window_start,
            "pickup_window_end": order.listing.pickup_window_end,
            "picked_up_at": order.picked_up_at,
            "created_at": order.created_at,
            "reviewed": order.id in reviewed_order_ids,
        }
        for order in orders
    ]
