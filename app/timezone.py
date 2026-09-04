from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

ALMATY_TZ = ZoneInfo("Asia/Almaty")


def parse_hhmm_today_almaty(text: str) -> Optional[datetime]:
    """Parse an HH:MM string as today's date in Asia/Almaty, return UTC-aware datetime."""
    text = text.strip()
    try:
        hour, minute = (int(p) for p in text.split(":"))
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    now_almaty = datetime.now(ALMATY_TZ)
    local_dt = now_almaty.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return local_dt.astimezone(timezone.utc)


def format_almaty(dt: datetime) -> str:
    """Format a UTC-aware (or naive-as-UTC) datetime as HH:MM in Asia/Almaty."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ALMATY_TZ).strftime("%H:%M")
