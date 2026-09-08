from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Fixed set of surprise-bag categories. Deliberately vague — enforces the
# "surprise" mechanic by construction, not just by merchant convention.
LISTING_CATEGORIES = (
    "bakery",
    "cafe_lunch",
    "restaurant_meal",
    "grocery",
    "other",
)

CATEGORY_LABELS = {
    "bakery": "Bakery surprise bag",
    "cafe_lunch": "Cafe lunch box",
    "restaurant_meal": "Restaurant surprise meal",
    "grocery": "Grocery surprise box",
    "other": "Surprise bag",
}

MERCHANT_DESCRIPTION_MAX_LEN = 100


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    location_text: Mapped[str] = mapped_column(String, nullable=False)
    # TODO: no geocoding step in merchant onboarding yet — coordinates are
    # set by hand (see seed_merchant.py) until registration exists.
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    contact_phone: Mapped[str] = mapped_column(String, nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    # Storefront/merchant photo shown on all of this merchant's listings.
    # Never a photo of a specific bag's contents — set once, reused everywhere.
    photo_file_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Short tagline describing the merchant generally (e.g. "Fresh sourdough
    # and pastries daily") — not an itemized description of bag contents,
    # which stays forbidden at the Listing level. Capped at MERCHANT_DESCRIPTION_MAX_LEN.
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    listings: Mapped[list["Listing"]] = relationship(back_populates="merchant")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    no_show_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    orders: Mapped[list["Order"]] = relationship(back_populates="user")


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        CheckConstraint(
            f"category IN ({', '.join(repr(c) for c in LISTING_CATEGORIES)})",
            name="ck_listings_category",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False)
    # Category only, never an itemized description of what's actually in the
    # bag — the "surprise" mechanic is the point. See LISTING_CATEGORIES.
    category: Mapped[str] = mapped_column(String, nullable=False)
    original_price: Mapped[int] = mapped_column(Integer, nullable=False)
    discounted_price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_total: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    pickup_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pickup_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    merchant: Mapped["Merchant"] = relationship(back_populates="listings")
    orders: Mapped[list["Order"]] = relationship(back_populates="listing")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="reserved")
    payment_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    pickup_code: Mapped[str] = mapped_column(String, nullable=False)
    picked_up_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    listing: Mapped["Listing"] = relationship(back_populates="orders")
    user: Mapped["User"] = relationship(back_populates="orders")


class Review(Base):
    """Three separate 1-5 ratings (TooGoodToGo-style), not one overall
    score — quality_rating/quantity_rating/variety_rating each get their
    own CHECK constraint. The overall score is computed on read as their
    average (see reviews.py), never stored, consistent with how
    merchant_rating already avoids a stored running average.
    """

    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("quality_rating BETWEEN 1 AND 5", name="ck_reviews_quality_rating_range"),
        CheckConstraint("quantity_rating BETWEEN 1 AND 5", name="ck_reviews_quantity_rating_range"),
        CheckConstraint("variety_rating BETWEEN 1 AND 5", name="ck_reviews_variety_rating_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # unique=True enforces one review per order at the data level — not just
    # in application logic — since a completed pickup is the unit a review
    # attaches to, not a user/merchant pair (a repeat customer can review
    # each visit).
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False)
    quality_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    variety_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped["Order"] = relationship()
    user: Mapped["User"] = relationship()
    merchant: Mapped["Merchant"] = relationship()


REVIEW_COMMENT_MAX_LEN = 300
