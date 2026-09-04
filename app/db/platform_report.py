"""Internal-only platform performance summary. Not exposed via the bot
or API — just a script to run by hand instead of querying the DB
manually every time we want to check pilot performance.

    python -m app.db.platform_report [today|week|all_time]

Defaults to all_time if no window is given.
"""

from __future__ import annotations

import sys

from app.db.session import get_session
from app.services.reports import WINDOWS, platform_summary

WINDOW_LABELS = {
    "today": "Today",
    "week": "Last 7 days",
    "all_time": "All time",
}


def print_report(window: str) -> None:
    session = get_session()
    try:
        stats = platform_summary(session, window)
    finally:
        session.close()

    print(f"=== Platform summary: {WINDOW_LABELS[window]} ===")
    print(f"Bags sold (picked up): {stats['bags_sold']}")
    print(f"No-shows: {stats['no_shows']}")
    print(f"Total reservations made: {stats['total_reservations']}")
    print(f"GMV: {stats['gmv']} KZT")
    print(f"Commission rate: {stats['commission_rate']:.0%} (placeholder — no real terms set yet)")
    print(f"Commission revenue: {stats['commission_revenue']} KZT")
    print(f"No-show rate: {stats['no_show_rate']:.1%} (of resolved reservations: picked up or no-show)")


if __name__ == "__main__":
    window = sys.argv[1] if len(sys.argv) > 1 else "all_time"
    if window not in WINDOWS:
        print(f"Unknown window {window!r}. Choose one of: {', '.join(WINDOWS)}")
        sys.exit(1)
    print_report(window)
