"""Tester at valgfrie HI-node-entiteter følger aktiverte moduler."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))


def _install_homeassistant_stubs() -> None:
    """Gi plattformmodulene akkurat nok HA-API til å kunne lastes i unit-testene."""

    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    helpers = types.ModuleType("homeassistant.helpers")
    util = types.ModuleType("homeassistant.util")

    class Entity:
        pass

    class DeviceInfo(dict):
        def __init__(self, **kwargs):
            super().__init__(kwargs)

    platform_classes = {
        "switch": ("SwitchEntity",),
        "number": ("NumberEntity",),
        "sensor": ("SensorEntity",),
        "button": ("ButtonEntity",),
    }
    for platform, names in platform_classes.items():
        module = types.ModuleType(f"homeassistant.components.{platform}")
        for name in names:
            setattr(module, name, type(name, (), {}))
        sys.modules[module.__name__] = module

    number = sys.modules["homeassistant.components.number"]
    number.NumberMode = types.SimpleNamespace(BOX="box")

    binary_sensor = types.ModuleType("homeassistant.components.binary_sensor")
    binary_sensor.BinarySensorEntity = type("BinarySensorEntity", (), {})
    binary_sensor.BinarySensorDeviceClass = types.SimpleNamespace(
        CONNECTIVITY="connectivity"
    )
    sys.modules[binary_sensor.__name__] = binary_sensor

    network = types.ModuleType("homeassistant.helpers.network")
    network.get_url = lambda *args, **kwargs: "http://homeassistant.local"
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    device_registry.DeviceInfo = DeviceInfo
    entity = types.ModuleType("homeassistant.helpers.entity")
    entity.Entity = Entity
    dt = types.ModuleType("homeassistant.util.dt")
    dt.now = datetime.now

    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.components": components,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.network": network,
            "homeassistant.helpers.device_registry": device_registry,
            "homeassistant.helpers.entity": entity,
            "homeassistant.util": util,
            "homeassistant.util.dt": dt,
        }
    )


_install_homeassistant_stubs()

from hi_node import binary_sensor, button, number, sensor, switch  # noqa: E402
from hi_node.const import DOMAIN  # noqa: E402
from hi_node.features import binding, has_feature, normalize_entry_data  # noqa: E402


class _Runtime:
    def __init__(self, features: dict[str, bool]):
        self.entry = types.SimpleNamespace(entry_id="entry", title="Test")
        self.normalized = normalize_entry_data(
            {
                "features": features,
                "bindings": {
                    "climate_entity": "climate.test",
                    "temperature_entity": "sensor.test_temperature",
                    "heater_power_entity": "switch.harvia_power",
                },
                "modules": [
                    {"roles": {"oven": "switch.oven", "door": "switch.door", "light": "switch.light"}}
                ],
            }
        )

    def _oven_entity_id(self):
        return "switch.oven"

    def _harvia_available(self):
        return bool(
            has_feature(self.normalized, "harvia_12h")
            and binding(self.normalized, "heater_power_entity")
            and self._oven_entity_id()
        )


def _suffixes(platform, runtime: _Runtime) -> set[str]:
    found = []
    hass = types.SimpleNamespace(data={DOMAIN: {"entry": runtime}})
    asyncio.run(platform.async_setup_entry(hass, runtime.entry, found.extend))
    return {
        entity._attr_unique_id.removeprefix("entry_")
        for entity in found
    }


class EntityGatingTests(unittest.TestCase):
    def test_no_optional_features_hides_all_optional_entities(self):
        runtime = _Runtime(
            {
                "climate": False,
                "frost": False,
                "grunnvarme_quota": False,
                "grunnvarme_schedule": False,
                "harvia_12h": False,
                "override_timers": False,
                "runtime_alarm": False,
                "runtime_notify": False,
            }
        )

        self.assertNotIn("grunnvarme", _suffixes(switch, runtime))
        self.assertNotIn("grunnvarme_hours_per_day", _suffixes(number, runtime))
        self.assertNotIn("frostvakt", _suffixes(switch, runtime))
        self.assertNotIn("booking_c", _suffixes(number, runtime))
        self.assertNotIn(
            "grunnvarme_schedule_active",
            _suffixes(binary_sensor, runtime),
        )
        self.assertNotIn("harvia_last_reset", _suffixes(sensor, runtime))
        self.assertNotIn("harvia_reset", _suffixes(button, runtime))
        self.assertNotIn("override_remaining_oven", _suffixes(sensor, runtime))
        self.assertNotIn("override_minutes", _suffixes(number, runtime))
        self.assertNotIn("oven_mismatch", _suffixes(binary_sensor, runtime))
        self.assertNotIn("alarm_delay_seconds", _suffixes(number, runtime))

    def test_quota_and_schedule_gate_grunnvarme_entities_independently(self):
        quota = _Runtime(
            {"grunnvarme_quota": True, "grunnvarme_schedule": False}
        )
        schedule = _Runtime(
            {"grunnvarme_quota": False, "grunnvarme_schedule": True}
        )

        self.assertIn("grunnvarme", _suffixes(switch, quota))
        self.assertIn("grunnvarme_hours_per_day", _suffixes(number, quota))
        self.assertIn("grunnvarme", _suffixes(switch, schedule))
        self.assertNotIn(
            "grunnvarme_hours_per_day",
            _suffixes(number, schedule),
        )
        self.assertIn(
            "grunnvarme_schedule_active",
            _suffixes(binary_sensor, schedule),
        )

    def test_climate_frost_and_harvia_entities_exist_when_enabled(self):
        runtime = _Runtime(
            {
                "climate": True,
                "frost": True,
                "grunnvarme_quota": False,
                "grunnvarme_schedule": False,
                "harvia_12h": True,
            }
        )

        self.assertIn("booking_c", _suffixes(number, runtime))
        self.assertIn("frostvakt", _suffixes(switch, runtime))
        self.assertIn("frost_c", _suffixes(number, runtime))
        self.assertIn("harvia_last_reset", _suffixes(sensor, runtime))
        self.assertIn("harvia_reset", _suffixes(button, runtime))

    def test_phase_two_entities_follow_runtime_features(self):
        runtime = _Runtime(
            {
                "override_timers": True,
                "runtime_alarm": True,
                "runtime_notify": True,
            }
        )

        self.assertIn("override_remaining_oven", _suffixes(sensor, runtime))
        self.assertIn("override_remaining_door", _suffixes(sensor, runtime))
        self.assertIn("override_remaining_light", _suffixes(sensor, runtime))
        self.assertIn("override_minutes", _suffixes(number, runtime))
        self.assertIn("oven_mismatch", _suffixes(binary_sensor, runtime))
        self.assertIn("alarm_delay_seconds", _suffixes(number, runtime))


if __name__ == "__main__":
    unittest.main()
