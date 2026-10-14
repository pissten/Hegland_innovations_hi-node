"""HI-node: booking-hjerne, helsebom og HKL-ER6 med LAN foran WiFi."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))

from hi_node.brain import RoleState, decide, parse_command  # noqa: E402
from hi_node.calendar_feed import in_margin_window, parse_ical  # noqa: E402
from hi_node.dashboard import compile_message  # noqa: E402
from hi_node.health import HealthTracker  # noqa: E402
from hi_node.profiles import (  # noqa: E402
    entity_id_for,
    load_manifest,
    render_profile,
    slugify,
)


OSLO = timezone(timedelta(hours=2))
T0 = datetime(2026, 10, 14, 12, 0, tzinfo=OSLO)


def _state(**overrides) -> RoleState:
    base = dict(
        fallback=False,
        commands={"oven": False, "door": False, "light": False},
        events=[],
        overrides={"oven": False, "door": False, "light": False},
        margins={
            "oven": (90, 0),
            "door": (5, 10),
            "light": (5, 10),
        },
        grunnvarme_timeplan=False,
        grunnvarme_hours_per_day=0.0,
        grunnvarme_hours_today=0.0,
        frost_enabled=False,
        frost_c=20.0,
        temperature_c=None,
        oven_on_since=None,
        reset_hold_until=None,
    )
    base.update(overrides)
    return RoleState(**base)


class HealthTests(unittest.TestCase):
    def test_three_failures_one_minute_apart_enters_fallback(self):
        tracker = HealthTracker()
        self.assertFalse(tracker.fallback)
        tracker.record(False, T0)
        tracker.record(False, T0 + timedelta(seconds=30))
        self.assertEqual(tracker.failures, 1)
        self.assertFalse(tracker.fallback)
        tracker.record(False, T0 + timedelta(minutes=1))
        tracker.record(False, T0 + timedelta(minutes=2))
        self.assertTrue(tracker.fallback)
        self.assertEqual(tracker.failures, 3)

    def test_success_clears_fallback_immediately(self):
        tracker = HealthTracker()
        tracker.record(False, T0)
        tracker.record(False, T0 + timedelta(minutes=1))
        tracker.record(False, T0 + timedelta(minutes=2))
        self.assertTrue(tracker.record(True, T0 + timedelta(minutes=3)))
        self.assertFalse(tracker.fallback)
        self.assertEqual(tracker.failures, 0)


class BrainTests(unittest.TestCase):
    def test_webhook_drives_outputs_while_health_is_up(self):
        start = T0 + timedelta(hours=1)
        end = start + timedelta(hours=1)
        decision = decide(
            _state(
                commands={"oven": True, "door": False, "light": True},
                events=[(start, end)],
            ),
            T0,
        )
        self.assertTrue(decision.oven)
        self.assertFalse(decision.door)
        self.assertTrue(decision.light)
        self.assertEqual(decision.mode, "webhook")
        self.assertEqual(decision.reason, "booking")
        self.assertNotIn("output4", decision.as_roles())

    def test_ical_is_ignored_until_fallback(self):
        start = T0 - timedelta(minutes=10)
        end = T0 + timedelta(minutes=50)
        decision = decide(_state(events=[(start, end)]), T0)
        self.assertFalse(decision.oven)
        self.assertFalse(decision.door)
        self.assertFalse(decision.light)

    def test_fallback_uses_vaemt_margins(self):
        start = T0 + timedelta(minutes=60)
        end = start + timedelta(hours=1)
        oven = decide(_state(fallback=True, events=[(start, end)]), T0)
        self.assertTrue(oven.oven)
        self.assertFalse(oven.door)
        self.assertFalse(oven.light)
        self.assertEqual(oven.mode, "ical")

        door_start = T0 + timedelta(minutes=5)
        door = decide(
            _state(fallback=True, events=[(door_start, door_start + timedelta(hours=1))]),
            T0,
        )
        self.assertTrue(door.door)
        self.assertTrue(door.light)
        self.assertTrue(door.oven)

        after = end + timedelta(minutes=10)
        closed = decide(_state(fallback=True, events=[(start, end)]), after)
        self.assertFalse(closed.oven)
        self.assertTrue(closed.door)
        self.assertTrue(closed.light)

    def test_manual_override_beats_booking(self):
        decision = decide(
            _state(
                commands={"oven": False, "door": False, "light": False},
                overrides={"oven": True, "door": False, "light": False},
            ),
            T0,
        )
        self.assertTrue(decision.oven)
        self.assertEqual(decision.reason, "manual_override")

    def test_grunnvarme_waits_until_booking_is_off(self):
        during = decide(
            _state(
                commands={"oven": True, "door": False, "light": False},
                grunnvarme_timeplan=True,
            ),
            T0,
        )
        self.assertEqual(during.reason, "booking")
        idle = decide(_state(grunnvarme_timeplan=True), T0)
        self.assertTrue(idle.oven)
        self.assertEqual(idle.reason, "grunnvarme")

    def test_frost_is_last_and_needs_temperature(self):
        missing = decide(_state(frost_enabled=True, temperature_c=None), T0)
        self.assertFalse(missing.oven)
        cold = decide(_state(frost_enabled=True, temperature_c=5.0, frost_c=20.0), T0)
        self.assertTrue(cold.oven)
        self.assertEqual(cold.reason, "frostvakt")

    def test_twelve_hour_guard_turns_oven_off(self):
        decision = decide(
            _state(
                commands={"oven": True, "door": True, "light": False},
                oven_on_since=T0 - timedelta(hours=12),
            ),
            T0,
        )
        self.assertFalse(decision.oven)
        self.assertTrue(decision.door)
        self.assertEqual(decision.reason, "heater_12h")


class CommandTests(unittest.TestCase):
    def test_booking_action_names(self):
        self.assertEqual(parse_command({"role": "ovn", "on": True}), ("oven", True))
        self.assertEqual(parse_command({"action": "dør", "state": "off"}), ("door", False))
        self.assertEqual(parse_command({"role": "lys", "on": False}), ("light", False))
        self.assertIsNone(parse_command({"role": "output4", "on": True}))


class CalendarTests(unittest.TestCase):
    def test_parse_and_window(self):
        text = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20261014T100000Z
DTEND:20261014T110000Z
END:VEVENT
END:VCALENDAR
"""
        events = parse_ical(text)
        self.assertEqual(len(events), 1)
        start, end = events[0]
        now = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
        self.assertTrue(in_margin_window(now, events, pre_min=90, post_min=0))
        self.assertFalse(in_margin_window(now, events, pre_min=5, post_min=10))
        self.assertEqual(start, datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 10, 14, 11, 0, tzinfo=timezone.utc))


class ProfileTests(unittest.TestCase):
    def test_manifest_offers_existing_and_hkl(self):
        manifest = load_manifest()
        ids = [item["id"] for item in manifest["profiles"]]
        self.assertEqual(ids, ["existing_switches", "hkl_er6"])
        hkl = manifest["profiles"][1]
        self.assertEqual(hkl["roles"]["oven"], "output1")
        self.assertEqual(hkl["roles"]["door"], "output2")
        self.assertEqual(hkl["roles"]["light"], "output3")
        self.assertEqual(hkl["network"]["priority"], ["ethernet", "wifi"])

    def test_render_prefers_lan_and_keeps_new_keys_only(self):
        yaml = render_profile(
            "hkl_er6",
            device_name="hi-vaemt",
            friendly_name="Væmt",
            api_key="NEWKEY",
            ota_password="NEWOTA",
            ap_password="NEWAP",
        )
        priority = yaml.split("priority:", 1)[1]
        self.assertLess(priority.index("ethernet"), priority.index("wifi"))
        self.assertIn("type: W5500", yaml)
        self.assertIn("clk_pin: GPIO13", yaml)
        self.assertIn("mosi_pin: GPIO11", yaml)
        self.assertIn("miso_pin: GPIO12", yaml)
        self.assertIn("cs_pin: GPIO14", yaml)
        self.assertIn("interrupt_pin: GPIO10", yaml)
        self.assertIn("reset_pin: GPIO9", yaml)
        self.assertIn('key: "NEWKEY"', yaml)
        self.assertIn('password: "NEWOTA"', yaml)
        self.assertIn("!secret wifi_ssid", yaml)
        self.assertIn("!secret wifi_password", yaml)
        self.assertNotIn("manual_ip:", yaml)
        self.assertIn('name: "output4"', yaml)
        self.assertIn('name: "output6"', yaml)
        self.assertIn("address: 0x24", yaml)
        self.assertIn("address: 0x25", yaml)
        self.assertNotIn("/8WlLJF9", yaml)
        self.assertNotIn("e2dd6a6ee0301b1d5ac4aa80b0f88c23", yaml)
        self.assertNotIn("dallas_temp", yaml)

    def test_static_lan_address_is_optional(self):
        yaml = render_profile(
            "hkl_er6",
            device_name="hi-kaia",
            friendly_name="Kaia",
            api_key="K",
            ota_password="O",
            ap_password="A",
            static_ip="192.168.50.40",
            gateway="192.168.50.1",
            subnet="255.255.255.0",
        )
        self.assertIn("static_ip: 192.168.50.40", yaml)
        self.assertIn("gateway: 192.168.50.1", yaml)
        self.assertIn("subnet: 255.255.255.0", yaml)

    def test_catalog_matches_the_component(self):
        for name in ("manifest.yaml", "hkl_er6.yaml"):
            packaged = (ROOT / "custom_components" / "hi_node" / "profiles" / name).read_text()
            catalog = (ROOT / "esphome" / "profiles" / name).read_text()
            self.assertEqual(packaged, catalog)

    def test_entity_ids_follow_esphome_names(self):
        self.assertEqual(slugify("Væmt"), "vaemt")
        self.assertEqual(entity_id_for("hi-vaemt", "output1"), "switch.hi_vaemt_output1")
        self.assertEqual(entity_id_for("hi-vaemt", "output2"), "switch.hi_vaemt_output2")
        self.assertEqual(entity_id_for("hi-vaemt", "output3"), "switch.hi_vaemt_output3")


class DashboardTests(unittest.TestCase):
    def test_compile_message_names_the_yaml(self):
        message = compile_message("hi-vaemt.yaml", "42")
        self.assertEqual(message["command"], "firmware/compile")
        self.assertEqual(message["message_id"], "42")
        self.assertEqual(message["args"]["configuration"], "hi-vaemt.yaml")


if __name__ == "__main__":
    unittest.main()
