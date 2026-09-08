from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import REVIEW_COMMENT_MAX_LEN, Order, Review, User


class ReviewError(Exception):
    """Raised when a review can't be posted."""


def _validate_rating(value: int, label: str) -> None:
    if value not in (1, 2, 3, 4, 5):
        raise ReviewError(f"{label} rating must be between 1 and 5.")


def submit_review(
    session: Session,
    user: User,
    order_id: int,
    quality_rating: int,
    quantity_rating: int,
    variety_rating: int,
    comment: str | None,
) -> Review:
    """Post a review for a completed pickup. Only the user who actually
    picked up that order may review it, and only once per order — enforced
    here (order ownership, pickup status) and at the DB level (order_id
    unique constraint on reviews), not just by this check.

    Three separate 1-5 ratings, TooGoodToGo-style — no single "rating"
    field. The overall score shown on cards is computed on read from
    these three (see merchant_ratings_bulk), never stored.
    """
    _validate_rating(quality_rating, "Quality")
    _validate_rating(quantity_rating, "Quantity")
    _validate_rating(variety_rating, "Variety")

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
        quality_rating=quality_rating,
        quantity_rating=quantity_rating,
        variety_rating=variety_rating,
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


def _overall_expr():
    """Per-review overall score: the average of the three dimension
    ratings for that single review. Used inside SQL aggregates below so
    the DB computes both the per-review overall and the cross-review
    average in one query, rather than pulling rows into Python.
    """
    return (Review.quality_rating + Review.quantity_rating + Review.variety_rating) / 3.0


def merchant_ratings_bulk(session: Session, merchant_ids: list[int]) -> dict[int, dict]:
    """Overall rating + count for many merchants in one query (so listing a
    page of cards doesn't run one query per card), recalculated on read
    rather than a stored running average, to avoid drift. Overall = the
    average of each review's three dimension ratings, then averaged across
    all of a merchant's reviews — never stored, per Review's own docstring.
    """
    rows = (
        session.query(Review.merchant_id, func.avg(_overall_expr()), func.count(Review.id))
        .filter(Review.merchant_id.in_(merchant_ids))
        .group_by(Review.merchant_id)
        .all()
    )
    return {
        merchant_id: {"average": round(float(avg), 1), "count": count}
        for merchant_id, avg, count in rows
    }


def merchant_rating_breakdown(session: Session, merchant_id: int) -> dict:
    """Per-dimension averages (quality/quantity/variety) plus the overall
    and count, for the merchant detail screen — the one place this app
    shows the breakdown rather than just a single compact number.
    """
    quality_avg, quantity_avg, variety_avg, count = (
        session.query(
            func.avg(Review.quality_rating),
            func.avg(Review.quantity_rating),
            func.avg(Review.variety_rating),
            func.count(Review.id),
        )
        .filter(Review.merchant_id == merchant_id)
        .one()
    )
    if count == 0:
        return {"quality": None, "quantity": None, "variety": None, "overall": None, "count": 0}

    quality_avg = float(quality_avg)
    quantity_avg = float(quantity_avg)
    variety_avg = float(variety_avg)
    overall = (quality_avg + quantity_avg + variety_avg) / 3.0
    return {
        "quality": round(quality_avg, 1),
        "quantity": round(quantity_avg, 1),
        "variety": round(variety_avg, 1),
        "overall": round(overall, 1),
        "count": count,
    }
