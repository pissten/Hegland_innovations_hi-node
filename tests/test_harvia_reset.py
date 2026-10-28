"""Harvia 12t-reset: parsing, triggergating og dual-cycle."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))

from hi_node import harvia_reset  # noqa: E402
from hi_node.harvia_reset import (  # noqa: E402
    automatic_reset_reason,
    parse_remaining_minutes,
    run_reset_cycle,
)


class RemainingMinutesTests(unittest.TestCase):
    def test_parses_hour_minute_and_hour_minute_second_values(self):
        self.assertEqual(parse_remaining_minutes("00:05"), 5)
        self.assertEqual(parse_remaining_minutes("12:34"), 12 * 60 + 34)
        self.assertEqual(parse_remaining_minutes("01:02:59"), 62)
        self.assertEqual(parse_remaining_minutes(" 5 "), 5)

    def test_rejects_unavailable_and_invalid_values(self):
        for value in (None, "", "unknown", "unavailable", "none", "1:99", "abc"):
            with self.subTest(value=value):
                self.assertIsNone(parse_remaining_minutes(value))


class AutomaticResetReasonTests(unittest.TestCase):
    def test_feature_and_oven_desire_gate_all_automatic_resets(self):
        common = {
            "heater_limit_reached": True,
            "remaining_minutes": 0,
            "power_is_on": False,
            "remaining_low_handled": False,
            "power_off_handled": False,
            "in_booking": False,
        }
        self.assertIsNone(
            automatic_reset_reason(
                feature_enabled=False,
                oven_desired=True,
                **common,
            )
        )
        self.assertIsNone(
            automatic_reset_reason(
                feature_enabled=True,
                oven_desired=False,
                **common,
            )
        )

    def test_selects_heater_feedback_periodic_and_preemptive_reasons(self):
        base = {
            "feature_enabled": True,
            "oven_desired": True,
            "heater_limit_reached": False,
            "remaining_minutes": None,
            "power_is_on": True,
            "remaining_low_handled": False,
            "power_off_handled": False,
            "in_booking": False,
        }
        cases = (
            ({"heater_limit_reached": True}, "heater_12h"),
            ({"power_is_on": False}, "feedback"),
            ({"remaining_minutes": 0}, "periodic"),
            ({"remaining_minutes": 5}, "preemptive"),
            ({"remaining_minutes": 30}, "preemptive_gap"),
        )
        for changes, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    automatic_reset_reason(**{**base, **changes}),
                    expected,
                )

    def test_soft_preemptive_waits_during_booking(self):
        self.assertIsNone(
            automatic_reset_reason(
                feature_enabled=True,
                oven_desired=True,
                heater_limit_reached=False,
                remaining_minutes=30,
                power_is_on=True,
                remaining_low_handled=False,
                power_off_handled=False,
                in_booking=True,
            )
        )

    def test_critical_preemptive_runs_during_booking(self):
        self.assertEqual(
            automatic_reset_reason(
                feature_enabled=True,
                oven_desired=True,
                heater_limit_reached=False,
                remaining_minutes=4,
                power_is_on=True,
                remaining_low_handled=False,
                power_off_handled=False,
                in_booking=True,
            ),
            "preemptive",
        )

    def test_latches_prevent_repeat_for_stale_low_and_off_states(self):
        self.assertIsNone(
            automatic_reset_reason(
                feature_enabled=True,
                oven_desired=True,
                heater_limit_reached=False,
                remaining_minutes=0,
                power_is_on=False,
                remaining_low_handled=True,
                power_off_handled=True,
                in_booking=False,
            )
        )


class _FakeServices:
    def __init__(self) -> None:
        self.calls = []

    async def async_call(self, domain, service, data, *, blocking):
        self.calls.append((domain, service, data, blocking))


class _FakeHass:
    def __init__(self) -> None:
        self.services = _FakeServices()


class ResetCycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_services_in_vaemt_order(self):
        hass = _FakeHass()
        old_off = harvia_reset.RESET_POWER_OFF_SECONDS
        old_on = harvia_reset.RESET_POWER_ON_WAIT_SECONDS
        harvia_reset.RESET_POWER_OFF_SECONDS = 0
        harvia_reset.RESET_POWER_ON_WAIT_SECONDS = 0
        try:
            await run_reset_cycle(
                hass,
                "switch.hkl_er6_output1",
                "switch.vaemt_power_switch",
            )
        finally:
            harvia_reset.RESET_POWER_OFF_SECONDS = old_off
            harvia_reset.RESET_POWER_ON_WAIT_SECONDS = old_on

        self.assertEqual(
            hass.services.calls,
            [
                (
                    "switch",
                    "turn_off",
                    {"entity_id": "switch.hkl_er6_output1"},
                    True,
                ),
                (
                    "switch",
                    "turn_off",
                    {"entity_id": "switch.vaemt_power_switch"},
                    True,
                ),
                (
                    "switch",
                    "turn_on",
                    {"entity_id": "switch.vaemt_power_switch"},
                    True,
                ),
                (
                    "switch",
                    "turn_on",
                    {"entity_id": "switch.hkl_er6_output1"},
                    True,
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
