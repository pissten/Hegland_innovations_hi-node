"""Oppsettsskjema for ett anlegg og flere I/O-kort."""

from __future__ import annotations

import base64
import os
import secrets

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .config_helpers import (
    build_features_from_user_input,
    build_schedule_from_user_input,
    dedupe_modules,
    is_duplicate_module,
    validate_bindings,
    validate_schedule_input,
)
from .const import DOMAIN, ROLES
from .features import (
    DEFAULT_BINDINGS,
    DEFAULT_FEATURES,
    DEFAULT_RUNTIME,
    DEFAULT_SCHEDULE,
    DEFAULT_TEMPS,
    normalize_entry_data,
)
from .profiles import device_name_for, entity_id_for, load_manifest, profile_by_id, slugify

_SWITCH = EntitySelector(EntitySelectorConfig(domain="switch"))
_TEMPERATURE = EntitySelector(EntitySelectorConfig(domain="sensor"))
_CLIMATE = EntitySelector(EntitySelectorConfig(domain="climate"))
_NOTIFY = EntitySelector(EntitySelectorConfig(domain="notify"))
_NUMBER = NumberSelector(
    NumberSelectorConfig(min=0, max=150, step=1, mode=NumberSelectorMode.BOX)
)
_CORE_FEATURE_KEYS = (
    "climate",
    "frost",
    "grunnvarme_quota",
    "grunnvarme_schedule",
    "harvia_12h",
)
_DRIFT_FEATURE_KEYS = ("override_timers", "runtime_alarm", "runtime_notify")
_WEEKDAYS = SelectSelector(
    SelectSelectorConfig(
        options=[
            {"label": "Mandag", "value": "0"},
            {"label": "Tirsdag", "value": "1"},
            {"label": "Onsdag", "value": "2"},
            {"label": "Torsdag", "value": "3"},
            {"label": "Fredag", "value": "4"},
            {"label": "Lørdag", "value": "5"},
            {"label": "Søndag", "value": "6"},
        ],
        multiple=True,
        mode=SelectSelectorMode.LIST,
    )
)


def _profile_selector():
    options = [
        {"label": item["name"], "value": item["id"]}
        for item in load_manifest()["profiles"]
    ]
    return SelectSelector(
        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
    )


def _features_schema(current: dict | None = None) -> vol.Schema:
    values = {**DEFAULT_FEATURES, **(current or {})}
    return vol.Schema(
        {
            vol.Required(key, default=bool(values[key])): bool
            for key in _CORE_FEATURE_KEYS
        }
    )


def _drift_schema(
    current_features: dict | None = None,
    current_runtime: dict | None = None,
) -> vol.Schema:
    features = {**DEFAULT_FEATURES, **(current_features or {})}
    runtime = {**DEFAULT_RUNTIME, **(current_runtime or {})}
    return vol.Schema(
        {
            **{
                vol.Required(key, default=bool(features[key])): bool
                for key in _DRIFT_FEATURE_KEYS
            },
            vol.Required(
                "override_minutes",
                default=runtime["override_minutes"],
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=1440,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                "alarm_delay_seconds",
                default=runtime["alarm_delay_seconds"],
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=600,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
    )


def _entity_marker(key: str, current: str | None, required: bool):
    marker = vol.Required if required else vol.Optional
    return marker(key, default=current) if current else marker(key)


def _bindings_schema(features: dict, current: dict | None = None) -> vol.Schema:
    values = {**DEFAULT_BINDINGS, **(current or {})}
    fields = {}
    if features.get("climate"):
        fields[_entity_marker("climate_entity", values["climate_entity"], True)] = (
            _CLIMATE
        )
    if features.get("frost"):
        needs_temperature = not features.get("climate")
        fields[
            _entity_marker(
                "temperature_entity",
                values["temperature_entity"],
                needs_temperature,
            )
        ] = _TEMPERATURE
    if features.get("harvia_12h"):
        fields[
            _entity_marker(
                "heater_power_entity",
                values["heater_power_entity"],
                True,
            )
        ] = _SWITCH
        fields[
            _entity_marker(
                "remaining_time_entity",
                values["remaining_time_entity"],
                False,
            )
        ] = _TEMPERATURE
    if features.get("runtime_notify"):
        fields[
            _entity_marker(
                "notify_entity",
                values.get("notify_entity") or values.get("notify_service"),
                True,
            )
        ] = _NOTIFY
    return vol.Schema(fields)


def _bindings_from_user_input(user_input: dict) -> dict:
    return {
        key: user_input.get(key) or None
        for key in DEFAULT_BINDINGS
    }


def _schedule_schema(current: dict | None = None) -> vol.Schema:
    values = {**DEFAULT_SCHEDULE, **(current or {})}
    return vol.Schema(
        {
            vol.Required(
                "weekdays",
                default=[str(day) for day in values["weekdays"]],
            ): _WEEKDAYS,
            vol.Required("start", default=values["start"]): str,
            vol.Required("end", default=values["end"]): str,
        }
    )


def _temps_schema(current: dict | None = None) -> vol.Schema:
    values = {**DEFAULT_TEMPS, **(current or {})}
    return vol.Schema(
        {
            vol.Required(key, default=values[key]): _NUMBER
            for key in DEFAULT_TEMPS
        }
    )


def _url_ok(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(part.isdigit() and 0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False


def _ip_error(user_input: dict) -> str | None:
    fields = [
        (user_input.get("static_ip") or "").strip(),
        (user_input.get("gateway") or "").strip(),
        (user_input.get("subnet") or "").strip(),
    ]
    if not any(fields):
        return None
    if not all(fields) or not all(_ipv4(item) for item in fields):
        return "ip"
    return None


def _new_secrets() -> dict:
    return {
        "api_key": base64.b64encode(os.urandom(32)).decode(),
        "ota_password": secrets.token_hex(16),
        "ap_password": secrets.token_hex(16),
    }


def build_module(profile_id: str, slug: str, index: int, user_input: dict) -> dict:
    """Ett kort. HKL-ER6 får nye nøkler og låste roller. Brytere peker på valgte entiteter."""
    info = profile_by_id(profile_id)
    if info.get("writes_firmware"):
        device_name = device_name_for(slug, index)
        module = {
            "profile": profile_id,
            "device_name": device_name,
            "roles": {
                role: entity_id_for(device_name, output)
                for role, output in info["roles"].items()
            },
            "static_ip": (user_input.get("static_ip") or "").strip(),
            "gateway": (user_input.get("gateway") or "").strip(),
            "subnet": (user_input.get("subnet") or "").strip(),
        }
        module.update(_new_secrets())
        return module
    return {
        "profile": profile_id,
        "device_name": "",
        "roles": {role: user_input[role] for role in ROLES},
    }


def module_label(index: int, module: dict) -> str:
    """Lesbar linje for I/O-listen i options."""
    roles = module.get("roles") or {}
    profile = module.get("profile") or "?"
    device = (module.get("device_name") or "").strip()
    head = device or profile
    return (
        f"{index + 1}. {head} — "
        f"ovn={roles.get('oven') or '-'}, "
        f"dør={roles.get('door') or '-'}, "
        f"lys={roles.get('light') or '-'}"
    )


def modules_description(modules: list) -> str:
    if not modules:
        return "Ingen I/O-bindinger er lagret ennå."
    lines = ["Allerede lagret:"]
    lines.extend(module_label(index, module) for index, module in enumerate(modules))
    return "\n".join(lines)


class _FeatureStepsMixin:
    """Felles modulsteg for første oppsett og options."""

    _draft: dict

    async def async_step_drift(self, user_input=None):
        if user_input is not None:
            features = dict(self._draft["features"])
            for key in _DRIFT_FEATURE_KEYS:
                features[key] = bool(user_input[key])
            self._draft["features"] = features
            self._draft["runtime"] = {
                key: user_input[key]
                for key in DEFAULT_RUNTIME
            }
            return await self.async_step_bindings()
        return self.async_show_form(
            step_id="drift",
            data_schema=_drift_schema(
                self._draft.get("features"),
                self._draft.get("runtime"),
            ),
        )

    async def async_step_bindings(self, user_input=None):
        errors = {}
        features = self._draft["features"]
        if user_input is not None:
            bindings = _bindings_from_user_input(user_input)
            error = validate_bindings(features, bindings)
            if error:
                errors["base"] = error
            else:
                self._draft["bindings"] = bindings
                if features["grunnvarme_schedule"]:
                    return await self.async_step_schedule()
                if features["climate"] or features["frost"]:
                    return await self.async_step_temps()
                return await self._async_finish_feature_flow()
        return self.async_show_form(
            step_id="bindings",
            data_schema=_bindings_schema(
                features,
                self._draft.get("bindings"),
            ),
            errors=errors,
        )

    async def async_step_schedule(self, user_input=None):
        errors = {}
        if user_input is not None:
            error = validate_schedule_input(user_input)
            if error:
                errors["base"] = error
            else:
                self._draft["schedule"] = build_schedule_from_user_input(user_input)
                features = self._draft["features"]
                if features["climate"] or features["frost"]:
                    return await self.async_step_temps()
                return await self._async_finish_feature_flow()
        return self.async_show_form(
            step_id="schedule",
            data_schema=_schedule_schema(self._draft.get("schedule")),
            errors=errors,
        )

    async def async_step_temps(self, user_input=None):
        if user_input is not None:
            self._draft["temps"] = {
                key: user_input[key]
                for key in DEFAULT_TEMPS
            }
            return await self._async_finish_feature_flow()
        return self.async_show_form(
            step_id="temps",
            data_schema=_temps_schema(self._draft.get("temps")),
        )

    async def _async_finish_feature_flow(self):
        raise NotImplementedError


class ConfigFlow(_FeatureStepsMixin, config_entries.ConfigFlow, domain=DOMAIN):
    """Ett skjema per anlegg."""

    VERSION = 1

    def __init__(self) -> None:
        self._draft: dict = {}

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            if not _url_ok(user_input["ical_url"]) or not _url_ok(user_input["health_url"]):
                errors["base"] = "url"
            else:
                self._draft.update(user_input)
                return await self.async_step_io()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("site_name"): str,
                    vol.Required("ical_url"): str,
                    vol.Required("health_url"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_io(self, user_input=None):
        if user_input is not None:
            self._draft["profile"] = user_input["profile"]
            if user_input["profile"] == "existing_switches":
                return await self.async_step_switches()
            return await self.async_step_hkl_er6()
        return self.async_show_form(
            step_id="io",
            data_schema=vol.Schema({vol.Required("profile"): _profile_selector()}),
        )

    async def async_step_switches(self, user_input=None):
        errors = {}
        if user_input is not None:
            if not all(user_input.get(role) for role in ROLES):
                errors["base"] = "switches"
            else:
                self._draft["module_input"] = dict(user_input)
                return await self.async_step_modules()
        return self.async_show_form(
            step_id="switches",
            data_schema=vol.Schema(
                {
                    vol.Required("oven"): _SWITCH,
                    vol.Required("door"): _SWITCH,
                    vol.Required("light"): _SWITCH,
                }
            ),
            errors=errors,
        )

    async def async_step_hkl_er6(self, user_input=None):
        errors = {}
        if user_input is not None:
            error = _ip_error(user_input)
            dashboard = (user_input.get("dashboard_url") or "").strip()
            if error:
                errors["base"] = error
            elif dashboard and not _url_ok(dashboard):
                errors["base"] = "url"
            else:
                self._draft["dashboard_url"] = dashboard
                self._draft["module_input"] = dict(user_input)
                return await self.async_step_modules()
        return self.async_show_form(
            step_id="hkl_er6",
            data_schema=vol.Schema(
                {
                    vol.Optional("static_ip", default=""): str,
                    vol.Optional("gateway", default=""): str,
                    vol.Optional("subnet", default=""): str,
                    vol.Optional("dashboard_url", default=""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_modules(self, user_input=None):
        if user_input is not None:
            self._draft["features"] = build_features_from_user_input(user_input)
            self._draft["runtime"] = dict(DEFAULT_RUNTIME)
            return await self.async_step_drift()
        return self.async_show_form(
            step_id="modules",
            data_schema=_features_schema(),
        )

    async def _async_finish_feature_flow(self):
        return await self._async_create()

    async def _async_create(self):
        site_name = self._draft["site_name"]
        slug = slugify(site_name)
        await self.async_set_unique_id(slug)
        self._abort_if_unique_id_configured()
        module = build_module(
            self._draft["profile"],
            slug,
            1,
            self._draft["module_input"],
        )
        data = normalize_entry_data(
            {
                "name": site_name,
                "slug": slug,
                "ical_url": self._draft["ical_url"].strip(),
                "health_url": self._draft["health_url"].strip(),
                "dashboard_url": self._draft.get("dashboard_url") or "",
                "features": self._draft["features"],
                "bindings": self._draft.get("bindings", {}),
                "schedule": self._draft.get("schedule", {}),
                "temps": self._draft.get("temps", {}),
                "runtime": self._draft.get("runtime", {}),
                "modules": [module],
            }
        )
        return self.async_create_entry(
            title=site_name,
            data=data,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler()


class OptionsFlowHandler(_FeatureStepsMixin, config_entries.OptionsFlow):
    """Legg til I/O-kort eller oppdater funksjoner og bindinger."""

    def __init__(self) -> None:
        super().__init__()
        self._profile: str | None = None
        self._draft: dict = {}

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_io", "manage_io", "features"],
        )

    async def async_step_add_io(self, user_input=None):
        if user_input is not None:
            self._profile = user_input["profile"]
            if user_input["profile"] == "existing_switches":
                return await self.async_step_switches()
            return await self.async_step_hkl_er6()
        current = normalize_entry_data(dict(self.config_entry.data))
        return self.async_show_form(
            step_id="add_io",
            data_schema=vol.Schema({vol.Required("profile"): _profile_selector()}),
            description_placeholders={
                "modules": modules_description(current.get("modules") or [])
            },
        )

    async def async_step_manage_io(self, user_input=None):
        data = normalize_entry_data(dict(self.config_entry.data))
        raw_modules = list(data.get("modules") or [])
        modules = dedupe_modules(raw_modules)
        if modules != raw_modules:
            data["modules"] = modules
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)
        if not modules:
            return self.async_abort(reason="no_modules")
        options = [
            {"value": str(index), "label": module_label(index, module)}
            for index, module in enumerate(modules)
        ]
        if user_input is not None:
            remove = {str(value) for value in (user_input.get("remove") or [])}
            kept = dedupe_modules(
                [
                    module
                    for index, module in enumerate(modules)
                    if str(index) not in remove
                ]
            )
            data["modules"] = kept
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.config_entry.entry_id)
            )
            return self.async_create_entry(title="", data={})
        return self.async_show_form(
            step_id="manage_io",
            data_schema=vol.Schema(
                {
                    vol.Optional("remove", default=[]): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            description_placeholders={"modules": modules_description(modules)},
        )

    async def async_step_features(self, user_input=None):
        current = normalize_entry_data(dict(self.config_entry.data))
        if user_input is not None:
            features = dict(current["features"])
            features.update(
                {
                    key: bool(user_input.get(key, DEFAULT_FEATURES[key]))
                    for key in _CORE_FEATURE_KEYS
                }
            )
            self._draft = {
                "features": features,
                "bindings": current["bindings"],
                "schedule": current["schedule"],
                "temps": current["temps"],
                "runtime": current["runtime"],
            }
            return await self.async_step_drift()
        return self.async_show_form(
            step_id="features",
            data_schema=_features_schema(current["features"]),
        )

    async def async_step_switches(self, user_input=None):
        errors = {}
        current = normalize_entry_data(dict(self.config_entry.data))
        if user_input is not None:
            if not all(user_input.get(role) for role in ROLES):
                errors["base"] = "switches"
            else:
                return self._add(user_input)
        return self.async_show_form(
            step_id="switches",
            data_schema=vol.Schema(
                {
                    vol.Required("oven"): _SWITCH,
                    vol.Required("door"): _SWITCH,
                    vol.Required("light"): _SWITCH,
                }
            ),
            errors=errors,
            description_placeholders={
                "modules": modules_description(current.get("modules") or [])
            },
        )

    async def async_step_hkl_er6(self, user_input=None):
        errors = {}
        if user_input is not None:
            error = _ip_error(user_input)
            if error:
                errors["base"] = error
            else:
                return self._add(user_input)
        return self.async_show_form(
            step_id="hkl_er6",
            data_schema=vol.Schema(
                {
                    vol.Optional("static_ip", default=""): str,
                    vol.Optional("gateway", default=""): str,
                    vol.Optional("subnet", default=""): str,
                }
            ),
            errors=errors,
        )

    def _add(self, user_input: dict):
        data = normalize_entry_data(dict(self.config_entry.data))
        modules = dedupe_modules(list(data.get("modules") or []))
        candidate = build_module(
            self._profile, data["slug"], len(modules) + 1, user_input
        )
        if is_duplicate_module(modules, candidate):
            if modules != list(data.get("modules") or []):
                data["modules"] = modules
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=data
                )
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(self.config_entry.entry_id)
                )
            return self.async_abort(reason="module_exists")
        modules.append(candidate)
        data["modules"] = modules
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self.config_entry.entry_id)
        )
        return self.async_create_entry(title="", data={})

    async def _async_finish_feature_flow(self):
        data = normalize_entry_data(dict(self.config_entry.data))
        data["features"] = self._draft["features"]
        data["bindings"] = self._draft["bindings"]
        data["schedule"] = self._draft["schedule"]
        data["temps"] = self._draft["temps"]
        data["runtime"] = self._draft["runtime"]
        data = normalize_entry_data(data)
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self.config_entry.entry_id)
        )
        return self.async_create_entry(title="", data={})
