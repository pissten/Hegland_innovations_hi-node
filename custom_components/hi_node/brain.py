"""Booking-hjernen. Integrasjonen bestemmer. Kortet er bare brytere."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .calendar_feed import in_margin_window
from .const import HEATER_LIMIT_HOURS, ROLE_ALIASES, ROLES


@dataclass
class RoleState:
    """Alt hjernen trenger for ett tidspunkt."""

    fallback: bool
    commands: dict
    events: list
    overrides: dict
    margins: dict
    grunnvarme_timeplan: bool = False
    grunnvarme_hours_per_day: float = 0.0
    grunnvarme_hours_today: float = 0.0
    frost_enabled: bool = False
    frost_c: float = 20.0
    temperature_c: float | None = None
    oven_on_since: datetime | None = None
    reset_hold_until: datetime | None = None


@dataclass
class Decision:
    """Ønsket tilstand for de tre rollene booking får styre."""

    oven: bool
    door: bool
    light: bool
    mode: str
    reason: str
    roles: dict = field(init=False)

    def __post_init__(self) -> None:
        self.roles = {"oven": self.oven, "door": self.door, "light": self.light}

    def as_roles(self) -> dict:
        return dict(self.roles)


def parse_command(payload: dict) -> tuple[str, bool] | None:
    """Oversett én webhook til rolle og på/av. Andre utganger slipper ikke inn."""
    if not isinstance(payload, dict):
        return None
    raw_role = str(payload.get("role") or payload.get("action") or "").strip().lower()
    role = ROLE_ALIASES.get(raw_role)
    if role not in ROLES:
        return None
    if "on" in payload:
        return role, bool(payload["on"])
    state = str(payload.get("state", "")).strip().lower()
    if state in ("on", "true", "1"):
        return role, True
    if state in ("off", "false", "0"):
        return role, False
    return None


def decide(state: RoleState, now: datetime) -> Decision:
    """Velg ovn, dør og lys. Utgang 4–6 er ikke med."""
    mode = "ical" if state.fallback else "webhook"
    source = {role: _source_on(state, role, now) for role in ROLES}
    door = bool(state.overrides.get("door")) or source["door"]
    light = bool(state.overrides.get("light")) or source["light"]

    if state.reset_hold_until is not None and now < state.reset_hold_until:
        return Decision(False, door, light, mode, "heater_12h")

    if state.overrides.get("oven"):
        oven, reason = True, "manual_override"
    elif source["oven"]:
        oven, reason = True, "booking"
    elif _grunnvarme(state, now, source["oven"]):
        oven, reason = True, "grunnvarme"
    elif _frost(state, source["oven"]):
        oven, reason = True, "frostvakt"
    else:
        oven, reason = False, "default_off"

    if oven and state.oven_on_since is not None:
        if now - state.oven_on_since >= timedelta(hours=HEATER_LIMIT_HOURS):
            oven, reason = False, "heater_12h"
    return Decision(oven, door, light, mode, reason)


def _source_on(state: RoleState, role: str, now: datetime) -> bool:
    if state.fallback:
        pre, post = state.margins[role]
        return in_margin_window(now, state.events, int(pre), int(post))
    return bool(state.commands.get(role, False))


def _grunnvarme(state: RoleState, now: datetime, source_oven: bool) -> bool:
    if source_oven:
        return False
    timeplan = bool(state.grunnvarme_timeplan)
    behov = (
        state.grunnvarme_hours_per_day > 0
        and state.grunnvarme_hours_today < state.grunnvarme_hours_per_day
    )
    return (behov or timeplan) and (timeplan or _after_last(state, now))


def _after_last(state: RoleState, now: datetime) -> bool:
    """Siste booking som berører dagen er ferdig."""
    latest = None
    today = now.date()
    for start, end in state.events:
        if now.tzinfo is not None and getattr(start, "tzinfo", None) is not None:
            start = start.astimezone(now.tzinfo)
            end = end.astimezone(now.tzinfo)
        if start.date() <= today <= end.date() or end.date() == today:
            if latest is None or end > latest:
                latest = end
    return latest is not None and now >= latest


def _frost(state: RoleState, source_oven: bool) -> bool:
    if source_oven or not state.frost_enabled or state.temperature_c is None:
        return False
    return state.temperature_c < state.frost_c
