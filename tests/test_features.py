"""Tester migrering og oppslag for HI-node-funksjoner."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))

from hi_node.features import (  # noqa: E402
    DEFAULT_BINDINGS,
    DEFAULT_FEATURES,
    DEFAULT_RUNTIME,
    DEFAULT_SCHEDULE,
    DEFAULT_TEMPS,
    binding,
    has_feature,
    normalize_entry_data,
    schedule_active,
)


class FeatureMigrationTests(unittest.TestCase):
    def test_empty_old_entry_gets_defaults(self):
        normalized = normalize_entry_data({})

        self.assertEqual(normalized["features"], DEFAULT_FEATURES)
        self.assertEqual(normalized["bindings"], DEFAULT_BINDINGS)
        self.assertEqual(normalized["schedule"], DEFAULT_SCHEDULE)
        self.assertEqual(normalized["temps"], DEFAULT_TEMPS)
        self.assertEqual(normalized["runtime"], DEFAULT_RUNTIME)
        self.assertTrue(normalized["features"]["override_timers"])
        self.assertFalse(normalized["features"]["runtime_alarm"])
        self.assertFalse(normalized["features"]["runtime_notify"])
        self.assertIsNone(normalized["bindings"]["notify_service"])

    def test_old_temperature_entity_moves_to_bindings_and_enables_frost(self):
        old = {"temperature_entity": "sensor.badstue_temperature"}

        normalized = normalize_entry_data(old)

        self.assertEqual(
            normalized["bindings"]["temperature_entity"],
            "sensor.badstue_temperature",
        )
        self.assertTrue(normalized["features"]["frost"])
        self.assertEqual(old, {"temperature_entity": "sensor.badstue_temperature"})

    def test_existing_features_bindings_and_other_data_are_preserved(self):
        modules = [{"profile": "existing_switches"}]
        old = {
            "name": "Væmt",
            "ical_url": "https://example.test/calendar",
            "modules": modules,
            "features": {"climate": True, "grunnvarme_quota": False},
            "bindings": {
                "climate_entity": "climate.vaemt",
                "temperature_entity": "sensor.preferred_temperature",
            },
            "temperature_entity": "sensor.legacy_temperature",
            "schedule": {"start": "08:00"},
            "temps": {"frost_c": 15},
            "runtime": {"override_minutes": 90},
        }

        normalized = normalize_entry_data(old)

        self.assertTrue(normalized["features"]["climate"])
        self.assertFalse(normalized["features"]["grunnvarme_quota"])
        self.assertEqual(
            normalized["bindings"]["temperature_entity"],
            "sensor.preferred_temperature",
        )
        self.assertEqual(normalized["schedule"]["start"], "08:00")
        self.assertEqual(normalized["schedule"]["end"], DEFAULT_SCHEDULE["end"])
        self.assertEqual(normalized["temps"]["frost_c"], 15)
        self.assertEqual(normalized["temps"]["booking_c"], DEFAULT_TEMPS["booking_c"])
        self.assertEqual(normalized["runtime"]["override_minutes"], 90)
        self.assertEqual(
            normalized["runtime"]["alarm_delay_seconds"],
            DEFAULT_RUNTIME["alarm_delay_seconds"],
        )
        self.assertEqual(normalized["ical_url"], old["ical_url"])
        self.assertIs(normalized["modules"], modules)
        self.assertIsNot(normalized, old)

    def test_frost_off_defaults_to_configured_grunnvarme_temperature(self):
        normalized = normalize_entry_data({"temps": {"grunnvarme_c": 35}})

        self.assertEqual(normalized["temps"]["frost_off_c"], 35)

    def test_feature_and_binding_helpers_use_normalized_data(self):
        data = normalize_entry_data(
            {
                "features": {"harvia_12h": True},
                "bindings": {"heater_power_entity": "switch.harvia_power"},
            }
        )

        self.assertTrue(has_feature(data, "harvia_12h"))
        self.assertFalse(has_feature(data, "frost"))
        self.assertFalse(has_feature(data, "unknown"))
        self.assertEqual(binding(data, "heater_power_entity"), "switch.harvia_power")
        self.assertIsNone(binding(data, "remaining_time_entity"))


class ScheduleTests(unittest.TestCase):
    def test_weekday_window_uses_monday_as_zero(self):
        schedule = {"weekdays": [0], "start": "06:00", "end": "22:00"}
        oslo = timezone(timedelta(hours=1))

        self.assertTrue(
            schedule_active(schedule, datetime(2026, 10, 26, 12, 0, tzinfo=oslo))
        )
        self.assertFalse(
            schedule_active(schedule, datetime(2026, 10, 27, 12, 0, tzinfo=oslo))
        )
        self.assertFalse(
            schedule_active(schedule, datetime(2026, 10, 26, 22, 0, tzinfo=oslo))
        )

    def test_overnight_window_continues_from_selected_weekday(self):
        schedule = {"weekdays": [0], "start": "22:00", "end": "06:00"}

        self.assertTrue(schedule_active(schedule, datetime(2026, 10, 26, 23, 0)))
        self.assertTrue(schedule_active(schedule, datetime(2026, 10, 27, 5, 59)))
        self.assertFalse(schedule_active(schedule, datetime(2026, 10, 27, 6, 0)))
        self.assertFalse(schedule_active(schedule, datetime(2026, 10, 27, 23, 0)))

    def test_invalid_or_empty_schedule_is_inactive(self):
        self.assertFalse(schedule_active({}, datetime(2026, 10, 26, 12, 0)))
        self.assertFalse(
            schedule_active(
                {"weekdays": [0], "start": "06:00", "end": "06:00"},
                datetime(2026, 10, 26, 12, 0),
            )
        )


if __name__ == "__main__":
    unittest.main()
