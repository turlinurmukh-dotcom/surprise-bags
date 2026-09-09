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
    # Second batch — fictional Almaty cafes/bakeries/restaurants, added for
    # broader merchant-list/map testing at a more realistic count. Explicitly
    # NOT real businesses — inventing a name rather than naming an actual
    # Almaty cafe avoids implying a real business offers surprise bags
    # without their consent.
    {
        "name": "Zolotoy Kolos Bakery",
        "location_text": "Gagarin Ave 105, near Kazakh-British Technical University, Almaty",
        "contact_phone": "+77010000007",
        "telegram_id": 900000007,
        "latitude": 43.2137,
        "longitude": 76.8975,
        "description": "Wood-fired bread and pastries since morning",
    },
    {
        "name": "Shanyrak Cafe",
        "location_text": "Rozybakiyev St 247, near KazNU main campus, Almaty",
        "contact_phone": "+77010000008",
        "telegram_id": 900000008,
        "latitude": 43.2015,
        "longitude": 76.9105,
        "description": "Home-style lunches, student-friendly prices",
    },
    {
        "name": "Nomad Kitchen",
        "location_text": "Nazarbayev Ave 130, near Almaty Mall, Almaty",
        "contact_phone": "+77010000009",
        "telegram_id": 900000009,
        "latitude": 43.2445,
        "longitude": 76.9464,
        "description": "Modern Kazakh-fusion dinners, evening surplus",
    },
    {
        "name": "Green Basket Market",
        "location_text": "Baizakov St 280, near Almaty Arena, Almaty",
        "contact_phone": "+77010000010",
        "telegram_id": 900000010,
        "latitude": 43.1998,
        "longitude": 76.8801,
        "description": "Neighborhood grocer, fresh produce daily",
    },
    {
        "name": "Dostyk Coffee House",
        "location_text": "Dostyk Ave 200, near Almaty Twin Towers, Almaty",
        "contact_phone": "+77010000011",
        "telegram_id": 900000011,
        "latitude": 43.2298,
        "longitude": 76.9553,
        "description": "Specialty coffee and light lunches all day",
    },
    {
        "name": "Baiterek Bistro",
        "location_text": "Abylai Khan Ave 63, near Almaty Tower, Almaty",
        "contact_phone": "+77010000012",
        "telegram_id": 900000012,
        "latitude": 43.2601,
        "longitude": 76.9451,
        "description": "Sit-down bistro, seasonal evening menu",
    },
    {
        "name": "Alatau Pekarnya",
        "location_text": "Timiryazev St 42, near KazNAU, Almaty",
        "contact_phone": "+77010000013",
        "telegram_id": 900000013,
        "latitude": 43.2079,
        "longitude": 76.9271,
        "description": "Family bakery, sourdough and sweet pastries",
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

        # Second batch — staggered across the day (late morning through late
        # evening) so the merchant list's soonest-pickup sort has real
        # variety to sort over, rather than everything clustered near "now".

        # Zolotoy Kolos Bakery — bakery, high quantity (bakeries produce
        # more units), afternoon pickup.
        ("Zolotoy Kolos Bakery", "bakery", 2400, 1000, 8, 8, timedelta(hours=2), timedelta(hours=3)),
        ("Zolotoy Kolos Bakery", "bakery", 1600, 700, 6, 6, timedelta(hours=5), timedelta(hours=6)),

        # Shanyrak Cafe — cafe_lunch, midday pickup, student-lunch pricing.
        ("Shanyrak Cafe", "cafe_lunch", 1800, 800, 5, 5, timedelta(hours=1), timedelta(hours=2)),

        # Nomad Kitchen — restaurant_meal, evening dinner pickup, lower
        # quantity than a bakery.
        ("Nomad Kitchen", "restaurant_meal", 4500, 2000, 3, 3, timedelta(hours=8), timedelta(hours=9, minutes=30)),
        ("Nomad Kitchen", "restaurant_meal", 3800, 1700, 2, 2, timedelta(hours=9), timedelta(hours=10)),

        # Green Basket Market — grocery, wide all-day pickup window,
        # moderate quantity.
        ("Green Basket Market", "grocery", 3000, 1400, 6, 6, timedelta(hours=3), timedelta(hours=11)),

        # Dostyk Coffee House — cafe_lunch, late-afternoon pickup.
        ("Dostyk Coffee House", "cafe_lunch", 2000, 900, 4, 4, timedelta(hours=6), timedelta(hours=7)),
        ("Dostyk Coffee House", "cafe_lunch", 1500, 650, 5, 5, timedelta(hours=6, minutes=30), timedelta(hours=7, minutes=30)),

        # Baiterek Bistro — restaurant_meal, evening pickup, lowest quantity
        # (sit-down restaurant, not a high-volume bakery).
        ("Baiterek Bistro", "restaurant_meal", 5000, 2200, 2, 2, timedelta(hours=10), timedelta(hours=11)),

        # Alatau Pekarnya — bakery, early-evening pickup, high quantity.
        ("Alatau Pekarnya", "bakery", 2200, 950, 7, 7, timedelta(hours=4), timedelta(hours=5)),
        ("Alatau Pekarnya", "bakery", 1400, 600, 5, 5, timedelta(hours=7), timedelta(hours=8)),
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
