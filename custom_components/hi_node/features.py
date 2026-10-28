"""Normalisering og oppslag for valgfrie HI-node-funksjoner."""

from __future__ import annotations

FEATURE_KEYS = (
    "climate",
    "frost",
    "grunnvarme_quota",
    "grunnvarme_schedule",
    "harvia_12h",
)

DEFAULT_FEATURES = {
    "climate": False,
    "frost": False,
    "grunnvarme_quota": True,
    "grunnvarme_schedule": False,
    "harvia_12h": False,
}

DEFAULT_BINDINGS = {
    "climate_entity": None,
    "temperature_entity": None,
    "heater_power_entity": None,
    "remaining_time_entity": None,
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

    if "climate" not in existing_features and bindings.get("climate_entity"):
        features["climate"] = True
    if "frost" not in existing_features and (
        bindings.get("temperature_entity") or bindings.get("climate_entity")
    ):
        features["frost"] = True

    existing_schedule = data.get("schedule")
    if not isinstance(existing_schedule, dict):
        existing_schedule = {}
    schedule = {**DEFAULT_SCHEDULE, **existing_schedule}
    if isinstance(schedule.get("weekdays"), list):
        schedule["weekdays"] = list(schedule["weekdays"])

    existing_temps = data.get("temps")
    if not isinstance(existing_temps, dict):
        existing_temps = {}

    normalized["features"] = features
    normalized["bindings"] = bindings
    normalized["schedule"] = schedule
    normalized["temps"] = {**DEFAULT_TEMPS, **existing_temps}
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
