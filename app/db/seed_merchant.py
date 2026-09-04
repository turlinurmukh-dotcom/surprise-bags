"""
TODO: There is no merchant registration/auth flow yet — that decision
(how a cafe owner first gets onboarded: self-serve /register command?
manual approval? an admin allowlist?) hasn't been made. There's also no
geocoding step — coordinates must be looked up and passed in by hand
(e.g. via Google Maps or 2GIS "copy coordinates") until that's built.

Until then, add merchants by hand with this script:

    python -m app.db.seed_merchant "Cafe Aroma" "Al-Farabi Ave 71, Almaty" \\
        "+77011234567" 123456789 43.2220 76.8512

The Telegram ID is the owner's numeric user ID (not username) — have
them message @userinfobot to get it. Lat/lng are optional; omit both
to leave the merchant unlocated (it just won't show up on the map view).
"""

import sys
from typing import Optional

from app.db.models import Merchant
from app.db.session import get_session


def seed_merchant(
    name: str,
    location_text: str,
    contact_phone: str,
    telegram_id: int,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> Merchant:
    session = get_session()
    try:
        existing = session.query(Merchant).filter_by(telegram_id=telegram_id).first()
        if existing:
            print(f"Merchant already exists: {existing.name} (id={existing.id})")
            return existing

        merchant = Merchant(
            name=name,
            location_text=location_text,
            contact_phone=contact_phone,
            telegram_id=telegram_id,
            latitude=latitude,
            longitude=longitude,
        )
        session.add(merchant)
        session.commit()
        session.refresh(merchant)
        print(f"Created merchant id={merchant.id}: {merchant.name}")
        return merchant
    finally:
        session.close()


if __name__ == "__main__":
    if len(sys.argv) not in (5, 7):
        print(
            "Usage: python -m app.db.seed_merchant <name> <location_text> "
            "<contact_phone> <telegram_id> [latitude longitude]"
        )
        sys.exit(1)

    lat = float(sys.argv[5]) if len(sys.argv) == 7 else None
    lng = float(sys.argv[6]) if len(sys.argv) == 7 else None

    seed_merchant(
        name=sys.argv[1],
        location_text=sys.argv[2],
        contact_phone=sys.argv[3],
        telegram_id=int(sys.argv[4]),
        latitude=lat,
        longitude=lng,
    )
