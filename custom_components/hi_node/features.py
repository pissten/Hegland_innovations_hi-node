"""Normalisering og oppslag for valgfrie HI-node-funksjoner."""

from __future__ import annotations

from datetime import datetime

FEATURE_KEYS = (
    "climate",
    "frost",
    "grunnvarme_quota",
    "grunnvarme_schedule",
    "harvia_12h",
    "override_timers",
    "runtime_alarm",
    "runtime_notify",
)

DEFAULT_FEATURES = {
    "climate": False,
    "frost": False,
    "grunnvarme_quota": True,
    "grunnvarme_schedule": False,
    "harvia_12h": False,
    "override_timers": True,
    "runtime_alarm": False,
    "runtime_notify": False,
}

DEFAULT_BINDINGS = {
    "climate_entity": None,
    "temperature_entity": None,
    "heater_power_entity": None,
    "remaining_time_entity": None,
    "notify_entity": None,
}

DEFAULT_SCHEDULE = {
    "weekdays": [0, 1, 2, 3, 4, 5, 6],
    "start": "06:00",
    "end": "22:00",
}

DEFAULT_TEMPS = {
    "booking_c": 110,
    "grunnvarme_c": 40,
    "default_c": 110,
    "frost_c": 20,
    "frost_hysteresis_c": 1,
    "frost_off_c": 40,
}

DEFAULT_RUNTIME = {
    "override_minutes": 60,
    "alarm_delay_seconds": 45,
}


def normalize_entry_data(data: dict) -> dict:
    """Fyll nytt config-schema uten å endre eller miste gammel entry-data."""
    normalized = dict(data)

    existing_features = data.get("features")
    if not isinstance(existing_features, dict):
        existing_features = {}
    features = {**DEFAULT_FEATURES, **existing_features}

    existing_bindings = data.get("bindings")
    if not isinstance(existing_bindings, dict):
        existing_bindings = {}
    bindings = {**DEFAULT_BINDINGS, **existing_bindings}

    legacy_temperature = data.get("temperature_entity")
    if not bindings.get("temperature_entity") and legacy_temperature:
        bindings["temperature_entity"] = legacy_temperature

    legacy_notify = bindings.pop("notify_service", None) or data.get("notify_service")
    if not bindings.get("notify_entity") and isinstance(legacy_notify, str):
        if legacy_notify.startswith("notify."):
            bindings["notify_entity"] = legacy_notify

    if "climate" not in existing_features and bindings.get("climate_entity"):
        features["climate"] = True
    if "frost" not in existing_features and (
        bindings.get("temperature_entity") or bindings.get("climate_entity")
    ):
        features["frost"] = True
    if "runtime_notify" not in existing_features and bindings.get("notify_entity"):
        features["runtime_notify"] = True

    existing_schedule = data.get("schedule")
    if not isinstance(existing_schedule, dict):
        existing_schedule = {}
    schedule = {**DEFAULT_SCHEDULE, **existing_schedule}
    if isinstance(schedule.get("weekdays"), list):
        schedule["weekdays"] = list(schedule["weekdays"])

    existing_temps = data.get("temps")
    if not isinstance(existing_temps, dict):
        existing_temps = {}
    temps = {**DEFAULT_TEMPS, **existing_temps}
    if "frost_off_c" not in existing_temps:
        temps["frost_off_c"] = temps.get("grunnvarme_c", 40)

    normalized["features"] = features
    normalized["bindings"] = bindings
    normalized["schedule"] = schedule
    normalized["temps"] = temps
    existing_runtime = data.get("runtime")
    if not isinstance(existing_runtime, dict):
        existing_runtime = {}
    normalized["runtime"] = {**DEFAULT_RUNTIME, **existing_runtime}
    return normalized


def has_feature(data: dict, name: str) -> bool:
    """Returner om en navngitt funksjon er aktivert."""
    features = data.get("features")
    return bool(isinstance(features, dict) and features.get(name))


def binding(data: dict, key: str) -> str | None:
    """Hent en entity-binding når verdien er en ikke-tom streng."""
    bindings = data.get("bindings")
    if not isinstance(bindings, dict):
        return None
    value = bindings.get(key)
    return value if isinstance(value, str) and value else None


def schedule_active(schedule: dict, now: datetime) -> bool:
    """Returner om lokal tid er innenfor valgt ukedag og klokkevindu."""
    if not isinstance(schedule, dict):
        return False
    try:
        weekdays = {int(day) for day in schedule.get("weekdays", ())}
        start = _clock_minutes(schedule.get("start"))
        end = _clock_minutes(schedule.get("end"))
    except (TypeError, ValueError):
        return False
    if not weekdays or start is None or end is None or start == end:
        return False

    minute = now.hour * 60 + now.minute
    weekday = now.weekday()
    if start < end:
        return weekday in weekdays and start <= minute < end
    if minute >= start:
        return weekday in weekdays
    return minute < end and (weekday - 1) % 7 in weekdays


def _clock_minutes(value) -> int | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) != 2 or any(len(part) != 2 or not part.isdigit() for part in parts):
        return None
    hour, minute = (int(part) for part in parts)
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute
