"""
Seeds realistic demo data for testing browsing, filtering, and the
responsive layout — safe to re-run without duplicating data.

    python -m app.db.seed_demo

Merchants are keyed by telegram_id (unique) — re-running skips ones that
already exist. Listings are keyed by (merchant, category, discounted_price,
quantity_total) as a fingerprint of "this exact demo listing" — re-running
skips ones already present rather than piling up duplicates.

Telegram IDs here are fake placeholders (900000001+), not real accounts —
these merchants exist for browsing/filtering data, not for testing the
merchant-side chat flow (use seed_merchant.py + your own account for that).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import Listing, Merchant
from app.db.session import get_session

DEMO_MERCHANTS = [
    {
        "name": "Sunny Bakery",
        "location_text": "Abay Ave 44, near KazNPU, Almaty",
        "contact_phone": "+77010000001",
        "telegram_id": 900000001,
        "latitude": 43.2385,
        "longitude": 76.9107,
    },
    {
        "name": "Campus Coffee Corner",
        "location_text": "Satpayev St 22, near KBTU, Almaty",
        "contact_phone": "+77010000002",
        "telegram_id": 900000002,
        "latitude": 43.2276,
        "longitude": 76.9046,
    },
    {
        "name": "Osken Restaurant",
        "location_text": "Tole Bi St 187, Almaty",
        "contact_phone": "+77010000003",
        "telegram_id": 900000003,
        "latitude": 43.2551,
        "longitude": 76.9286,
    },
    {
        "name": "Freshmart Grocery",
        "location_text": "Dostyk Ave 91, near Nazarbayev University area, Almaty",
        "contact_phone": "+77010000004",
        "telegram_id": 900000004,
        "latitude": 43.2189,
        "longitude": 76.9298,
    },
    {
        "name": "Corner Deli",
        "location_text": "Zhandosov St 58, near AUES, Almaty",
        "contact_phone": "+77010000005",
        "telegram_id": 900000005,
        "latitude": 43.2027,
        "longitude": 76.8794,
    },
    {
        "name": "Aroma Lunchbox",
        "location_text": "Al-Farabi Ave 71, near KazNU, Almaty",
        "contact_phone": "+77010000006",
        "telegram_id": 900000006,
        "latitude": 43.2224,
        "longitude": 76.9517,
    },
]


def _get_or_create_merchant(session, data: dict) -> tuple[Merchant, bool]:
    merchant = session.query(Merchant).filter_by(telegram_id=data["telegram_id"]).first()
    if merchant is not None:
        return merchant, False
    merchant = Merchant(**data)
    session.add(merchant)
    session.commit()
    session.refresh(merchant)
    return merchant, True


def _listing_exists(session, merchant_id: int, category: str, discounted_price: int, quantity_total: int) -> bool:
    return (
        session.query(Listing)
        .filter_by(
            merchant_id=merchant_id,
            category=category,
            discounted_price=discounted_price,
            quantity_total=quantity_total,
        )
        .first()
        is not None
    )


def seed_demo_data() -> None:
    session = get_session()
    now = datetime.now(timezone.utc)

    merchants = {}
    merchants_created = 0
    for data in DEMO_MERCHANTS:
        merchant, was_created = _get_or_create_merchant(session, data)
        merchants[data["name"]] = merchant
        if was_created:
            merchants_created += 1

    # (merchant_name, category, original_price, discounted_price, quantity_total,
    #  quantity_remaining, pickup_start_offset, pickup_end_offset)
    # Offsets are timedeltas from "now" — negative means already past.
    demo_listings = [
        # Sunny Bakery — bakery, one steep discount starting soon, one modest
        # discount later, one already expired (should never show in browse).
        ("Sunny Bakery", "bakery", 2800, 900, 4, 4, timedelta(minutes=30), timedelta(hours=2)),
        ("Sunny Bakery", "bakery", 1500, 1100, 3, 1, timedelta(hours=4), timedelta(hours=6)),
        ("Sunny Bakery", "bakery", 2000, 800, 2, 2, timedelta(hours=-6), timedelta(hours=-4)),

        # Campus Coffee Corner — cafe_lunch, plenty left, one down to last unit.
        ("Campus Coffee Corner", "cafe_lunch", 2200, 900, 6, 6, timedelta(hours=1), timedelta(hours=3)),
        ("Campus Coffee Corner", "cafe_lunch", 1800, 1400, 2, 1, timedelta(hours=2), timedelta(hours=4)),

        # Osken Restaurant — restaurant_meal, higher price point, modest discount.
        ("Osken Restaurant", "restaurant_meal", 7000, 3200, 3, 3, timedelta(hours=3), timedelta(hours=5)),
        ("Osken Restaurant", "restaurant_meal", 5500, 4200, 2, 2, timedelta(hours=5), timedelta(hours=7)),

        # Freshmart Grocery — grocery, one sold out (quantity_remaining=0 but
        # NOT expired — tests that sold-out is excluded for a different
        # reason than expiry), one with plenty left.
        ("Freshmart Grocery", "grocery", 4500, 1800, 5, 0, timedelta(hours=2), timedelta(hours=8)),
        ("Freshmart Grocery", "grocery", 3200, 1600, 8, 8, timedelta(hours=1), timedelta(hours=10)),

        # Corner Deli — other, steep discount, starting very soon.
        ("Corner Deli", "other", 1600, 500, 4, 4, timedelta(minutes=15), timedelta(hours=2)),
        ("Corner Deli", "other", 2400, 1900, 3, 2, timedelta(hours=6), timedelta(hours=9)),

        # Aroma Lunchbox — cafe_lunch, later today, last-unit urgency case.
        ("Aroma Lunchbox", "cafe_lunch", 2600, 1000, 5, 5, timedelta(hours=4), timedelta(hours=6)),
        ("Aroma Lunchbox", "cafe_lunch", 1900, 1500, 4, 1, timedelta(hours=7), timedelta(hours=9)),
    ]

    created = 0
    skipped = 0
    for (
        merchant_name,
        category,
        original_price,
        discounted_price,
        quantity_total,
        quantity_remaining,
        start_offset,
        end_offset,
    ) in demo_listings:
        merchant = merchants[merchant_name]
        if _listing_exists(session, merchant.id, category, discounted_price, quantity_total):
            skipped += 1
            continue

        status = "sold_out" if quantity_remaining == 0 else "active"
        listing = Listing(
            merchant_id=merchant.id,
            category=category,
            original_price=original_price,
            discounted_price=discounted_price,
            quantity_total=quantity_total,
            quantity_remaining=quantity_remaining,
            pickup_window_start=now + start_offset,
            pickup_window_end=now + end_offset,
            status=status,
        )
        session.add(listing)
        created += 1

    session.commit()

    print(f"Merchants: {len(DEMO_MERCHANTS)} total ({merchants_created} newly created, "
          f"{len(DEMO_MERCHANTS) - merchants_created} already existed)")
    print(f"Listings: {created} newly created, {skipped} already existed (skipped)")

    session.close()


if __name__ == "__main__":
    seed_demo_data()
