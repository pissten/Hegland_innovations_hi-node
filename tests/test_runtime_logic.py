"""Ren regresjonstest av fase 2-runtime uten Home Assistant."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))

from hi_node.runtime_logic import (  # noqa: E402
    expire_overrides,
    next_oven_mismatch,
    should_notify_alarm,
)

NOW = datetime(2026, 10, 28, 20, 0, tzinfo=timezone.utc)


class OverrideExpiryTests(unittest.TestCase):
    def test_expired_override_is_cleared_with_its_deadline(self):
        overrides = {"oven": True, "door": True, "light": False}
        deadlines = {
            "oven": (NOW - timedelta(seconds=1)).isoformat(),
            "door": (NOW + timedelta(minutes=1)).isoformat(),
            "light": None,
        }

        next_overrides, next_deadlines, changed = expire_overrides(
            overrides, deadlines, NOW
        )

        self.assertEqual(changed, {"oven"})
        self.assertFalse(next_overrides["oven"])
        self.assertIsNone(next_deadlines["oven"])
        self.assertTrue(next_overrides["door"])
        self.assertEqual(next_deadlines["door"], deadlines["door"])


class AlarmLogicTests(unittest.TestCase):
    def test_mismatch_must_be_continuous_for_configured_delay(self):
        since, alarm = next_oven_mismatch(
            None,
            desired_on=True,
            oven_on=False,
            power_on=True,
            now=NOW,
            delay_seconds=45,
        )
        self.assertEqual(since, NOW.isoformat())
        self.assertFalse(alarm)

        since, alarm = next_oven_mismatch(
            since,
            desired_on=True,
            oven_on=False,
            power_on=True,
            now=NOW + timedelta(seconds=44),
            delay_seconds=45,
        )
        self.assertFalse(alarm)

        since, alarm = next_oven_mismatch(
            since,
            desired_on=True,
            oven_on=False,
            power_on=True,
            now=NOW + timedelta(seconds=45),
            delay_seconds=45,
        )
        self.assertTrue(alarm)

    def test_matching_output_resets_mismatch_window(self):
        since, alarm = next_oven_mismatch(
            NOW.isoformat(),
            desired_on=True,
            oven_on=True,
            power_on=True,
            now=NOW + timedelta(minutes=1),
            delay_seconds=45,
        )

        self.assertIsNone(since)
        self.assertFalse(alarm)

    def test_harvia_power_must_also_be_on_when_bound(self):
        since, alarm = next_oven_mismatch(
            (NOW - timedelta(seconds=45)).isoformat(),
            desired_on=True,
            oven_on=True,
            power_on=False,
            now=NOW,
            delay_seconds=45,
        )

        self.assertIsNotNone(since)
        self.assertTrue(alarm)


class NotifyDebounceTests(unittest.TestCase):
    def test_notify_only_on_rising_alarm_edge(self):
        self.assertTrue(should_notify_alarm(False, True))
        self.assertFalse(should_notify_alarm(True, True))
        self.assertFalse(should_notify_alarm(True, False))
        self.assertFalse(should_notify_alarm(False, False))


if __name__ == "__main__":
    unittest.main()
