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
    grunnvarme_schedule_enabled: bool | None = None
    grunnvarme_in_schedule: bool = False
    grunnvarme_hours_per_day: float = 0.0
    grunnvarme_hours_today: float = 0.0
    frost_enabled: bool = False
    frost_calling: bool = False
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


_MONTHS = (
    "",
    "jan.",
    "feb.",
    "mars",
    "apr.",
    "mai",
    "juni",
    "juli",
    "aug.",
    "sep.",
    "okt.",
    "nov.",
    "des.",
)


def booking_event(
    now: datetime,
    events: list[tuple[datetime, datetime]],
    pre_min: int,
    post_min: int,
) -> tuple[datetime, datetime] | None:
    """Bookingen som gjør at ovnen skal kjøre nå (start og slutt)."""
    pre = timedelta(minutes=int(pre_min))
    post = timedelta(minutes=int(post_min))
    covering: list[tuple[datetime, datetime]] = []
    upcoming: list[tuple[datetime, datetime]] = []
    for start, end in events:
        if start - pre <= now <= end + post:
            covering.append((start, end))
        elif start > now:
            upcoming.append((start, end))
    if covering:
        started = [pair for pair in covering if pair[0] <= now]
        return max(started, key=lambda pair: pair[0]) if started else min(covering, key=lambda pair: pair[0])
    if upcoming:
        return min(upcoming, key=lambda pair: pair[0])
    return None


def booking_start(
    now: datetime,
    events: list[tuple[datetime, datetime]],
    pre_min: int,
    post_min: int,
) -> datetime | None:
    """Starten på bookingen som gjør at ovnen skal kjøre nå."""
    event = booking_event(now, events, pre_min, post_min)
    return None if event is None else event[0]


def oven_status(
    reason: str,
    start: datetime | None,
    now: datetime,
    duration_min: int | None = None,
) -> str:
    """Tekst til status-sensoren under ovnen."""
    if reason == "booking":
        if start is None:
            return "Booking"
        shown = start.astimezone(now.tzinfo) if now.tzinfo and start.tzinfo else start
        when = f"{shown.day}. {_MONTHS[shown.month]} kl. {shown:%H:%M}"
        if shown.year != now.year:
            when = f"{shown.day}. {_MONTHS[shown.month]} {shown.year} kl. {shown:%H:%M}"
        if duration_min is not None and duration_min > 0:
            return f"Booking {when} ({int(duration_min)} min)"
        return f"Booking {when}"
    return {
        "frostvakt": "Frostvakt",
        "grunnvarme": "Grunnvarme",
        "manual_override": "Manuell",
        "heater_12h": "12-timers pause",
        "default_off": "Av",
    }.get(reason, "Av")


def _source_on(state: RoleState, role: str, now: datetime) -> bool:
    """Kalenderen med før/etter gjelder alltid. Webhook kan i tillegg slå på."""
    pre, post = state.margins[role]
    in_window = in_margin_window(now, state.events, int(pre), int(post))
    if state.fallback:
        return in_window
    return bool(state.commands.get(role, False)) or in_window


def _grunnvarme(state: RoleState, now: datetime, source_oven: bool) -> bool:
    if source_oven:
        return False
    if state.grunnvarme_schedule_enabled is None:
        timeplan = bool(state.grunnvarme_timeplan)
    else:
        timeplan = (
            state.grunnvarme_schedule_enabled
            and state.grunnvarme_in_schedule
        )
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
    return bool(
        not source_oven
        and state.frost_enabled
        and state.frost_calling
    )


def next_frost_calling(
    *,
    previous: bool,
    feature_enabled: bool,
    switch_enabled: bool,
    temperature_c: float | None,
    frost_c: float,
    hysteresis_c: float,
    frost_off_c: float,
) -> bool:
    """Frost PÅ under frost_c−hysterese, AV ved frost_off_c.

    Mangler temperatur midlertidig (sensor unavailable) beholdes forrige
    tilstand, så korte dropp ikke togler ovnen.
    """
    if not feature_enabled or not switch_enabled:
        return False
    if temperature_c is None:
        return bool(previous)
    on_below = float(frost_c) - float(hysteresis_c)
    if temperature_c < on_below:
        return True
    if temperature_c >= float(frost_off_c):
        return False
    return bool(previous)
