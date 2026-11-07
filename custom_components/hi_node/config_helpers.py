"""Ren hjelpelogikk for modulbasert config flow."""

from __future__ import annotations

import re

from .features import DEFAULT_BINDINGS, DEFAULT_FEATURES, FEATURE_KEYS

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


def _filled_entity(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_bindings(features: dict, bindings: dict) -> dict[str, str]:
    """Feltfeil for manglende påkrevde bindinger (tom dict = ok).

    Feltene er tømbare i UI; denne sjekken stopper lagring til de er fylt
    (eller funksjonen er skrudd av).
    """
    errors: dict[str, str] = {}
    if features.get("climate") and not _filled_entity(bindings.get("climate_entity")):
        errors["climate_entity"] = "required_binding"
    if features.get("frost"):
        has_climate = _filled_entity(bindings.get("climate_entity"))
        has_temperature = _filled_entity(bindings.get("temperature_entity"))
        if not has_climate and not has_temperature:
            if features.get("climate"):
                errors.setdefault("climate_entity", "frost_binding")
            else:
                errors["temperature_entity"] = "frost_binding"
    if features.get("harvia_12h") and not _filled_entity(
        bindings.get("heater_power_entity")
    ):
        errors["heater_power_entity"] = "harvia_binding"
    if features.get("runtime_notify"):
        entity_id = bindings.get("notify_entity")
        if not isinstance(entity_id, str) or not entity_id.startswith("notify."):
            errors["notify_entity"] = "notify_binding"
    if errors:
        errors["base"] = "bindings_incomplete"
    return errors


def merge_bindings_from_input(user_input: dict, features: dict) -> dict:
    """Les bindinger fra skjema. Skjulte (deaktiverte) funksjoner tømmes."""
    merged = {key: None for key in DEFAULT_BINDINGS}
    if features.get("climate"):
        merged["climate_entity"] = user_input.get("climate_entity") or None
    if features.get("frost") or features.get("climate"):
        # temperatursensor kan vises ved frost; behold bare når feltet fantes
        if "temperature_entity" in user_input or features.get("frost"):
            merged["temperature_entity"] = user_input.get("temperature_entity") or None
    if features.get("harvia_12h"):
        merged["heater_power_entity"] = user_input.get("heater_power_entity") or None
        merged["remaining_time_entity"] = user_input.get("remaining_time_entity") or None
    if features.get("runtime_notify"):
        merged["notify_entity"] = user_input.get("notify_entity") or None
    return merged


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
