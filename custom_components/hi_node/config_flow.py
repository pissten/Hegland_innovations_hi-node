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
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import DOMAIN, ROLES
from .profiles import device_name_for, entity_id_for, load_manifest, profile_by_id, slugify

_SWITCH = EntitySelector(EntitySelectorConfig(domain="switch"))
_TEMPERATURE = EntitySelector(EntitySelectorConfig(domain="sensor"))


def _profile_selector():
    options = [
        {"label": item["name"], "value": item["id"]}
        for item in load_manifest()["profiles"]
    ]
    return SelectSelector(
        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
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


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
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
                    vol.Required("name"): str,
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
                self._draft["temperature_entity"] = user_input.get("temperature_entity") or ""
                return await self._async_create(user_input)
        return self.async_show_form(
            step_id="switches",
            data_schema=vol.Schema(
                {
                    vol.Required("oven"): _SWITCH,
                    vol.Required("door"): _SWITCH,
                    vol.Required("light"): _SWITCH,
                    vol.Optional("temperature_entity"): _TEMPERATURE,
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
                self._draft["temperature_entity"] = user_input.get("temperature_entity") or ""
                self._draft["dashboard_url"] = dashboard
                return await self._async_create(user_input)
        return self.async_show_form(
            step_id="hkl_er6",
            data_schema=vol.Schema(
                {
                    vol.Optional("static_ip", default=""): str,
                    vol.Optional("gateway", default=""): str,
                    vol.Optional("subnet", default=""): str,
                    vol.Optional("temperature_entity"): _TEMPERATURE,
                    vol.Optional("dashboard_url", default=""): str,
                }
            ),
            errors=errors,
        )

    async def _async_create(self, user_input: dict):
        slug = slugify(self._draft["name"])
        await self.async_set_unique_id(slug)
        self._abort_if_unique_id_configured()
        module = build_module(self._draft["profile"], slug, 1, user_input)
        return self.async_create_entry(
            title=self._draft["name"],
            data={
                "name": self._draft["name"],
                "slug": slug,
                "ical_url": self._draft["ical_url"].strip(),
                "health_url": self._draft["health_url"].strip(),
                "temperature_entity": self._draft.get("temperature_entity") or "",
                "dashboard_url": self._draft.get("dashboard_url") or "",
                "modules": [module],
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Legg til et kort fra samme liste."""

    def __init__(self) -> None:
        super().__init__()
        self._profile: str | None = None

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            self._profile = user_input["profile"]
            if user_input["profile"] == "existing_switches":
                return await self.async_step_switches()
            return await self.async_step_hkl_er6()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required("profile"): _profile_selector()}),
        )

    async def async_step_switches(self, user_input=None):
        errors = {}
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
        data = dict(self.config_entry.data)
        modules = list(data.get("modules") or [])
        modules.append(build_module(self._profile, data["slug"], len(modules) + 1, user_input))
        data["modules"] = modules
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self.config_entry.entry_id)
        )
        return self.async_create_entry(title="", data={})
