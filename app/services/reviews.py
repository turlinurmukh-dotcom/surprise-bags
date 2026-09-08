from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import REVIEW_COMMENT_MAX_LEN, Order, Review, User


class ReviewError(Exception):
    """Raised when a review can't be posted."""


def submit_review(
    session: Session, user: User, order_id: int, rating: int, comment: str | None
) -> Review:
    """Post a review for a completed pickup. Only the user who actually
    picked up that order may review it, and only once per order — enforced
    here (order ownership, pickup status) and at the DB level (order_id
    unique constraint on reviews), not just by this check.
    """
    if rating not in (1, 2, 3, 4, 5):
        raise ReviewError("Rating must be between 1 and 5.")

    comment = comment.strip() if comment else None
    if comment and len(comment) > REVIEW_COMMENT_MAX_LEN:
        raise ReviewError(f"Comment must be under {REVIEW_COMMENT_MAX_LEN} characters.")

    order = session.query(Order).filter_by(id=order_id).first()
    if order is None or order.user_id != user.id:
        raise ReviewError("Order not found.")
    if order.status != "picked_up":
        raise ReviewError("You can only review an order after you've picked it up.")

    existing = session.query(Review).filter_by(order_id=order_id).first()
    if existing is not None:
        raise ReviewError("You've already reviewed this order.")

    review = Review(
        order_id=order.id,
        user_id=user.id,
        merchant_id=order.listing.merchant_id,
        rating=rating,
        comment=comment,
    )
    session.add(review)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ReviewError("You've already reviewed this order.") from exc
    session.refresh(review)
    return review


def merchant_rating(session: Session, merchant_id: int) -> dict:
    """Average rating + count for a merchant, recalculated on read rather
    than a stored running average, to avoid drift.
    """
    avg, count = (
        session.query(func.avg(Review.rating), func.count(Review.id))
        .filter(Review.merchant_id == merchant_id)
        .one()
    )
    return {
        "average": round(float(avg), 1) if avg is not None else None,
        "count": count,
    }


def merchant_ratings_bulk(session: Session, merchant_ids: list[int]) -> dict[int, dict]:
    """Same as merchant_rating but for many merchants in one query, so
    listing a page of cards doesn't run one query per card.
    """
    rows = (
        session.query(Review.merchant_id, func.avg(Review.rating), func.count(Review.id))
        .filter(Review.merchant_id.in_(merchant_ids))
        .group_by(Review.merchant_id)
        .all()
    )
    return {
        merchant_id: {"average": round(float(avg), 1), "count": count}
        for merchant_id, avg, count in rows
    }
