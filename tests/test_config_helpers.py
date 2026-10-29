"""Tester ren hjelpelogikk for modulbasert config flow."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))

from hi_node.config_helpers import (  # noqa: E402
    build_features_from_user_input,
    build_schedule_from_user_input,
    dedupe_modules,
    is_duplicate_module,
    validate_bindings,
    validate_schedule_input,
)
from hi_node.features import DEFAULT_FEATURES  # noqa: E402


class ConfigHelperTests(unittest.TestCase):
    def test_feature_input_uses_defaults_for_missing_values(self):
        features = build_features_from_user_input({"climate": True, "frost": True})

        self.assertTrue(features["climate"])
        self.assertTrue(features["frost"])
        self.assertEqual(
            features["grunnvarme_quota"],
            DEFAULT_FEATURES["grunnvarme_quota"],
        )
        self.assertFalse(features["grunnvarme_schedule"])
        self.assertFalse(features["harvia_12h"])

    def test_frost_requires_climate_or_temperature_binding(self):
        features = build_features_from_user_input({"frost": True})

        self.assertEqual(validate_bindings(features, {}), "frost_binding")
        self.assertIsNone(
            validate_bindings(
                features,
                {"temperature_entity": "sensor.badstue_temperature"},
            )
        )
        self.assertIsNone(
            validate_bindings(
                features,
                {"climate_entity": "climate.badstue"},
            )
        )

    def test_harvia_requires_power_binding(self):
        features = build_features_from_user_input({"harvia_12h": True})

        self.assertEqual(validate_bindings(features, {}), "harvia_binding")
        self.assertIsNone(
            validate_bindings(
                features,
                {"heater_power_entity": "switch.harvia_power"},
            )
        )

    def test_notify_requires_notify_entity(self):
        features = build_features_from_user_input({"runtime_notify": True})

        self.assertEqual(validate_bindings(features, {}), "notify_binding")
        self.assertEqual(
            validate_bindings(features, {"notify_entity": "mobile_app_phone"}),
            "notify_binding",
        )
        self.assertIsNone(
            validate_bindings(
                features,
                {"notify_entity": "notify.mobile_app_phone"},
            )
        )

    def test_schedule_converts_weekdays_to_integers(self):
        schedule = build_schedule_from_user_input(
            {
                "weekdays": ["0", "2", "6"],
                "start": "07:30",
                "end": "21:45",
            }
        )

        self.assertEqual(schedule["weekdays"], [0, 2, 6])
        self.assertEqual(schedule["start"], "07:30")
        self.assertEqual(schedule["end"], "21:45")

    def test_schedule_requires_weekday_and_valid_clock_times(self):
        self.assertEqual(
            validate_schedule_input(
                {"weekdays": [], "start": "06:00", "end": "22:00"}
            ),
            "schedule",
        )
        self.assertEqual(
            validate_schedule_input(
                {"weekdays": ["0"], "start": "24:00", "end": "22:00"}
            ),
            "schedule",
        )
        self.assertEqual(
            validate_schedule_input(
                {"weekdays": ["0"], "start": "06:00:00", "end": "22:00"}
            ),
            "schedule",
        )
        self.assertIsNone(
            validate_schedule_input(
                {"weekdays": ["0"], "start": "06:00", "end": "22:00"}
            )
        )

    def test_identical_io_modules_are_ignored_as_duplicates(self):
        first = {
            "profile": "existing_switches",
            "roles": {
                "oven": "switch.hkl_er6_output1",
                "door": "switch.hkl_er6_output2",
                "light": "switch.hkl_er6_output3",
            },
        }
        same = dict(first)
        other = {
            "profile": "existing_switches",
            "roles": {
                "oven": "switch.other",
                "door": "switch.hkl_er6_output2",
                "light": "switch.hkl_er6_output3",
            },
        }
        self.assertTrue(is_duplicate_module([first], same))
        self.assertFalse(is_duplicate_module([first], other))
        self.assertEqual(dedupe_modules([first, same, other]), [first, other])


if __name__ == "__main__":
    unittest.main()
