"""Ren hjelpelogikk for modulbasert config flow."""

from __future__ import annotations

import re

from .features import DEFAULT_FEATURES, FEATURE_KEYS

_CLOCK_PATTERN = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


def module_binding_key(module: dict) -> tuple:
    """Identitet for et I/O-oppsett: profil + ovn/dør/lys."""
    roles = module.get("roles") or {}
    return (
        str(module.get("profile") or ""),
        str(roles.get("oven") or ""),
        str(roles.get("door") or ""),
        str(roles.get("light") or ""),
    )


def is_duplicate_module(modules: list, candidate: dict) -> bool:
    key = module_binding_key(candidate)
    return any(module_binding_key(module) == key for module in modules)


def dedupe_modules(modules: list) -> list:
    """Behold første av hvert like oppsett."""
    seen: set[tuple] = set()
    unique: list = []
    for module in modules:
        key = module_binding_key(module)
        if key in seen:
            continue
        seen.add(key)
        unique.append(module)
    return unique


def build_features_from_user_input(user_input: dict) -> dict:
    """Bygg en komplett feature-tabell fra et skjemasvar."""
    return {
        key: bool(user_input.get(key, DEFAULT_FEATURES[key]))
        for key in FEATURE_KEYS
    }


def validate_bindings(features: dict, bindings: dict) -> str | None:
    """Returner oversettelsesnøkkel for manglende påkrevd binding."""
    if (
        features.get("frost")
        and not bindings.get("climate_entity")
        and not bindings.get("temperature_entity")
    ):
        return "frost_binding"
    if features.get("harvia_12h") and not bindings.get("heater_power_entity"):
        return "harvia_binding"
    if features.get("runtime_notify"):
        entity_id = bindings.get("notify_entity")
        if not isinstance(entity_id, str) or not entity_id.startswith("notify."):
            return "notify_binding"
    return None


def validate_schedule_input(user_input: dict) -> str | None:
    """Valider at timeplanen har ukedager og klokkeslett i HH:MM-format."""
    if not user_input.get("weekdays"):
        return "schedule"
    if not all(
        isinstance(user_input.get(key), str)
        and _CLOCK_PATTERN.fullmatch(user_input[key])
        for key in ("start", "end")
    ):
        return "schedule"
    return None


def build_schedule_from_user_input(user_input: dict) -> dict:
    """Konverter skjemaverdier til lagringsformatet."""
    return {
        "weekdays": [int(day) for day in user_input["weekdays"]],
        "start": user_input["start"],
        "end": user_input["end"],
    }
