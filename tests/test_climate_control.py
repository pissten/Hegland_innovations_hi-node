"""Settpunktvalg for climate-modulen."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))

from hi_node.climate_control import target_c_for_reason  # noqa: E402


class ClimateControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temps = {
            "booking_c": 110,
            "grunnvarme_c": 40,
            "default_c": 75,
        }

    def test_booking_and_manual_override_use_booking_temperature(self):
        for reason in ("booking", "manual_override"):
            with self.subTest(reason=reason):
                self.assertEqual(target_c_for_reason(reason, self.temps), 110.0)

    def test_grunnvarme_and_frostvakt_use_grunnvarme_temperature(self):
        for reason in ("grunnvarme", "frostvakt"):
            with self.subTest(reason=reason):
                self.assertEqual(target_c_for_reason(reason, self.temps), 40.0)

    def test_other_reasons_use_default_temperature(self):
        for reason in ("default_off", "heater_12h", "ukjent"):
            with self.subTest(reason=reason):
                self.assertEqual(target_c_for_reason(reason, self.temps), 75.0)


if __name__ == "__main__":
    unittest.main()
