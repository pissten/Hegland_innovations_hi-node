"""Tester for grunnvarme-kalender lagring og utvidelse."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))

from hi_node.grunnvarme_calendar import (  # noqa: E402
    calendar_active,
    create_event_record,
    delete_event_record,
    ensure_seeded,
    expand_events,
    seed_from_schedule,
    update_event_record,
)

OSLO = timezone(timedelta(hours=1))


class GrunnvarmeCalendarTests(unittest.TestCase):
    def test_seed_weekly_window_from_schedule(self):
        events = seed_from_schedule(
            {"weekdays": [0, 2], "start": "06:00", "end": "22:00"},
            datetime(2026, 10, 26, 12, 0, tzinfo=OSLO),  # mandag
        )
        self.assertEqual(len(events), 1)
        self.assertIn("BYDAY=MO,WE", events[0]["rrule"])
        self.assertTrue(
            calendar_active(events, datetime(2026, 10, 26, 12, 0, tzinfo=OSLO))
        )
        self.assertFalse(
            calendar_active(events, datetime(2026, 10, 27, 12, 0, tzinfo=OSLO))
        )
        self.assertTrue(
            calendar_active(events, datetime(2026, 10, 28, 12, 0, tzinfo=OSLO))
        )

    def test_overnight_rrule_window(self):
        events = seed_from_schedule(
            {"weekdays": [0], "start": "22:00", "end": "06:00"},
            datetime(2026, 10, 26, 12, 0, tzinfo=OSLO),
        )
        self.assertTrue(
            calendar_active(events, datetime(2026, 10, 26, 23, 0, tzinfo=OSLO))
        )
        self.assertTrue(
            calendar_active(events, datetime(2026, 10, 27, 5, 59, tzinfo=OSLO))
        )
        self.assertFalse(
            calendar_active(events, datetime(2026, 10, 27, 6, 0, tzinfo=OSLO))
        )

    def test_ensure_seeded_keeps_existing(self):
        existing = [
            create_event_record(
                start=datetime(2026, 10, 26, 8, 0, tzinfo=OSLO),
                end=datetime(2026, 10, 26, 10, 0, tzinfo=OSLO),
                summary="Manuell",
            )
        ]
        kept = ensure_seeded(
            existing,
            {"weekdays": [0], "start": "06:00", "end": "22:00"},
            datetime(2026, 10, 26, 12, 0, tzinfo=OSLO),
        )
        self.assertEqual(kept[0]["summary"], "Manuell")

    def test_create_update_delete_roundtrip(self):
        events = []
        created = create_event_record(
            start=datetime(2026, 10, 26, 9, 0, tzinfo=OSLO),
            end=datetime(2026, 10, 26, 11, 0, tzinfo=OSLO),
            summary="Test",
        )
        events.append(created)
        self.assertTrue(
            calendar_active(events, datetime(2026, 10, 26, 10, 0, tzinfo=OSLO))
        )
        events = update_event_record(
            events,
            created["uid"],
            start=datetime(2026, 10, 26, 14, 0, tzinfo=OSLO),
            end=datetime(2026, 10, 26, 16, 0, tzinfo=OSLO),
        )
        self.assertFalse(
            calendar_active(events, datetime(2026, 10, 26, 10, 0, tzinfo=OSLO))
        )
        self.assertTrue(
            calendar_active(events, datetime(2026, 10, 26, 15, 0, tzinfo=OSLO))
        )
        events = delete_event_record(events, created["uid"])
        self.assertEqual(events, [])

    def test_expand_lists_occurrences_in_range(self):
        events = seed_from_schedule(
            {"weekdays": [0], "start": "06:00", "end": "08:00"},
            datetime(2026, 10, 26, 12, 0, tzinfo=OSLO),
        )
        items = expand_events(
            events,
            datetime(2026, 10, 26, 0, 0, tzinfo=OSLO),
            datetime(2026, 11, 10, 0, 0, tzinfo=OSLO),
        )
        self.assertGreaterEqual(len(items), 2)
        self.assertEqual(items[0]["start"].weekday(), 0)


if __name__ == "__main__":
    unittest.main()
