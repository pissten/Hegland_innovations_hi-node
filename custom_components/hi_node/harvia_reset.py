"""Dual-cycle som nullstiller Harvia sin interne 12-timer."""

from __future__ import annotations

import asyncio

RESET_POWER_OFF_SECONDS = 10
RESET_POWER_ON_WAIT_SECONDS = 8

_UNAVAILABLE_STATES = {"", "unknown", "unavailable", "none"}


def parse_remaining_minutes(state_str: str | None) -> int | None:
    """Les minutter fra Harvia-verdier som HH:MM, HH:MM:SS eller minutter."""
    if state_str is None:
        return None
    raw = str(state_str).strip().lower()
    if raw in _UNAVAILABLE_STATES:
        return None
    parts = raw.split(":")
    if len(parts) == 1:
        return int(parts[0]) if parts[0].isdigit() else None
    if len(parts) not in (2, 3) or any(not part.isdigit() for part in parts):
        return None
    hours, minutes = int(parts[0]), int(parts[1])
    if minutes > 59:
        return None
    if len(parts) == 3 and int(parts[2]) > 59:
        return None
    return hours * 60 + minutes


def automatic_reset_reason(
    *,
    feature_enabled: bool,
    oven_desired: bool,
    heater_limit_reached: bool,
    remaining_minutes: int | None,
    power_is_on: bool | None,
    remaining_low_handled: bool,
    power_off_handled: bool,
) -> str | None:
    """Velg én resetårsak, uten å repetere fastlåste sensorverdier."""
    if not feature_enabled or not oven_desired:
        return None
    if heater_limit_reached:
        return "heater_12h"
    if power_is_on is False and not power_off_handled:
        return "feedback"
    if remaining_minutes == 0 and not remaining_low_handled:
        return "periodic"
    if (
        remaining_minutes is not None
        and remaining_minutes <= 5
        and not remaining_low_handled
    ):
        return "preemptive"
    return None


async def run_reset_cycle(hass, oven_entity_id: str, power_entity_id: str) -> None:
    """Slå av ovn og Harvia-strøm, vent, og start dem igjen i riktig rekkefølge."""
    await _set_switch(hass, oven_entity_id, False)
    await _set_switch(hass, power_entity_id, False)
    await asyncio.sleep(RESET_POWER_OFF_SECONDS)
    await _set_switch(hass, power_entity_id, True)
    await asyncio.sleep(RESET_POWER_ON_WAIT_SECONDS)
    await _set_switch(hass, oven_entity_id, True)


async def _set_switch(hass, entity_id: str, on: bool) -> None:
    await hass.services.async_call(
        "switch",
        "turn_on" if on else "turn_off",
        {"entity_id": entity_id},
        blocking=True,
    )
