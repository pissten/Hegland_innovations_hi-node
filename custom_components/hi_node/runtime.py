"""Kjører booking-hjernen på noden og skriver ESPHome-oppsettet."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .brain import RoleState, decide, parse_command
from .calendar_feed import parse_ical
from .const import DEFAULT_MARGINS, DOMAIN, RESET_HOLD_SECONDS, ROLES
from .dashboard import compile_message, dashboard_candidates
from .health import HealthTracker
from .profiles import profile_by_id, render_profile

_LOGGER = logging.getLogger(__name__)


def _blank_state() -> dict:
    return {
        "commands": {role: False for role in ROLES},
        "overrides": {role: False for role in ROLES},
        "margins": {role: [pre, post] for role, (pre, post) in DEFAULT_MARGINS.items()},
        "events": [],
        "failures": 0,
        "fallback": False,
        "last_failure": None,
        "grunnvarme_timeplan": False,
        "grunnvarme_hours_per_day": 0,
        "grunnvarme_hours_today": 0,
        "grunnvarme_day": None,
        "grunnvarme_mark": None,
        "frost_enabled": False,
        "frost_c": 20,
        "oven_on_since": None,
        "reset_hold_until": None,
    }


class HiNodeRuntime:
    """Én oppføring, ett anlegg."""

    def __init__(self, hass, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.data = _blank_state()
        self.tracker = HealthTracker()
        self.decision = None
        self.webhook_id = f"{DOMAIN}_{entry.entry_id}"
        self._listeners: list = []
        self._unsubs: list = []

    def listen(self, update):
        self._listeners.append(update)

        def _remove():
            if update in self._listeners:
                self._listeners.remove(update)

        return _remove

    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    def modules(self) -> list:
        return list(self.entry.data.get("modules") or [])

    async def async_start(self) -> None:
        stored = await self.store.async_load()
        self.data = _blank_state()
        if stored:
            self.data.update(stored)
            self.data["commands"] = {**_blank_state()["commands"], **(stored.get("commands") or {})}
            self.data["overrides"] = {
                **_blank_state()["overrides"],
                **(stored.get("overrides") or {}),
            }
            self.data["margins"] = {**_blank_state()["margins"], **(stored.get("margins") or {})}
        self.tracker.failures = int(self.data.get("failures") or 0)
        self.tracker.fallback = bool(self.data.get("fallback"))
        last = self.data.get("last_failure")
        if last:
            self.tracker._last = dt_util.parse_datetime(last)
        webhook.async_register(
            self.hass,
            DOMAIN,
            "HI-node",
            self.webhook_id,
            self._webhook,
        )
        await self._write_firmware()
        await self._refresh_ical()
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(minutes=1)))
        self._unsubs.append(
            async_track_time_interval(self.hass, self._ical_tick, timedelta(minutes=15))
        )
        await self._tick(dt_util.now())

    async def async_stop(self) -> None:
        webhook.async_unregister(self.hass, self.webhook_id)
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def async_apply_now(self) -> None:
        await self._apply(dt_util.now())

    async def _webhook(self, hass, webhook_id, request):
        try:
            payload = await request.json()
        except Exception:
            return web.Response(status=400, text="json")
        parsed = parse_command(payload)
        if parsed is None:
            return web.Response(status=400, text="role")
        role, on = parsed
        self.data["commands"][role] = on
        await self._apply(dt_util.now())
        return web.Response(status=200, text="ok")

    async def _tick(self, now) -> None:
        now = dt_util.as_local(now)
        was_fallback = self.tracker.fallback
        ok = await self._health_ok()
        self.tracker.record(ok, now)
        if self.tracker.fallback and not was_fallback:
            await self._refresh_ical()
        self.data["failures"] = self.tracker.failures
        self.data["fallback"] = self.tracker.fallback
        self.data["last_failure"] = (
            self.tracker._last.isoformat() if self.tracker._last else None
        )
        self._roll_day(now)
        await self._apply(now)

    async def _ical_tick(self, now) -> None:
        await self._refresh_ical()
        await self._apply(dt_util.as_local(now))

    async def _health_ok(self) -> bool:
        url = self.entry.data.get("health_url")
        if not url:
            return False
        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(10):
                response = await session.get(url)
                return 200 <= response.status < 300
        except Exception:
            return False

    async def _refresh_ical(self) -> None:
        url = self.entry.data.get("ical_url")
        if not url:
            return
        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(20):
                response = await session.get(url)
                if response.status >= 300:
                    return
                text = await response.text()
            events = parse_ical(text)
        except Exception:
            _LOGGER.debug("Klarte ikke å hente iCal", exc_info=True)
            return
        self.data["events"] = [[start.isoformat(), end.isoformat()] for start, end in events]

    def _roll_day(self, now) -> None:
        day = now.date().isoformat()
        if self.data.get("grunnvarme_day") != day:
            self.data["grunnvarme_day"] = day
            self.data["grunnvarme_hours_today"] = 0
            self.data["grunnvarme_mark"] = None

    def role_state(self, now):
        margins = {
            role: tuple(self.data["margins"].get(role) or DEFAULT_MARGINS[role])
            for role in ROLES
        }
        return RoleState(
            fallback=self.tracker.fallback,
            commands=dict(self.data["commands"]),
            events=_events(self.data.get("events") or []),
            overrides=dict(self.data["overrides"]),
            margins=margins,
            grunnvarme_timeplan=bool(self.data.get("grunnvarme_timeplan")),
            grunnvarme_hours_per_day=float(self.data.get("grunnvarme_hours_per_day") or 0),
            grunnvarme_hours_today=float(self.data.get("grunnvarme_hours_today") or 0),
            frost_enabled=bool(self.data.get("frost_enabled")),
            frost_c=float(self.data.get("frost_c") or 20),
            temperature_c=self._temperature(),
            oven_on_since=_stamp(self.data.get("oven_on_since")),
            reset_hold_until=_stamp(self.data.get("reset_hold_until")),
        )

    def _temperature(self):
        entity_id = self.entry.data.get("temperature_entity")
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", "none", ""):
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    async def _apply(self, now) -> None:
        hold = _stamp(self.data.get("reset_hold_until"))
        if hold is not None and now >= hold:
            self.data["reset_hold_until"] = None
        state = self.role_state(now)
        decision = decide(state, now)
        if decision.reason == "heater_12h" and state.oven_on_since is not None:
            self.data["reset_hold_until"] = (
                now + timedelta(seconds=RESET_HOLD_SECONDS)
            ).isoformat()
            self.data["oven_on_since"] = None
            decision = decide(self.role_state(now), now)
        self._count_grunnvarme(decision, now)
        if decision.oven and not self.data.get("oven_on_since") and decision.reason != "heater_12h":
            self.data["oven_on_since"] = now.isoformat()
        if not decision.oven and decision.reason != "heater_12h":
            self.data["oven_on_since"] = None
        self.decision = decision
        for module in self.modules():
            for role, entity_id in (module.get("roles") or {}).items():
                if role in ROLES and entity_id:
                    await self._set_switch(entity_id, bool(getattr(decision, role)))
        await self.store.async_save(self.data)
        self._notify()

    def _count_grunnvarme(self, decision, now) -> None:
        mark = _stamp(self.data.get("grunnvarme_mark"))
        if decision.reason == "grunnvarme":
            if mark is not None:
                hours = max(0.0, (now - mark).total_seconds() / 3600)
                self.data["grunnvarme_hours_today"] = float(self.data.get("grunnvarme_hours_today") or 0) + hours
            self.data["grunnvarme_mark"] = now.isoformat()
        else:
            self.data["grunnvarme_mark"] = None

    async def _set_switch(self, entity_id: str, on: bool) -> None:
        current = self.hass.states.get(entity_id)
        if current is None or current.state in ("unknown", "unavailable"):
            return
        desired = "on" if on else "off"
        if current.state == desired:
            return
        service = "turn_on" if on else "turn_off"
        await self.hass.services.async_call(
            "switch",
            service,
            {"entity_id": entity_id},
            blocking=False,
        )

    async def _write_firmware(self) -> None:
        for module in self.modules():
            info = _profile(module.get("profile"))
            if not info or not info.get("writes_firmware"):
                continue
            content = render_profile(
                module["profile"],
                device_name=module["device_name"],
                friendly_name=self.entry.data.get("name") or module["device_name"],
                api_key=module["api_key"],
                ota_password=module["ota_password"],
                ap_password=module["ap_password"],
                static_ip=module.get("static_ip") or None,
                gateway=module.get("gateway") or None,
                subnet=module.get("subnet") or None,
            )
            filename = f"{module['device_name']}.yaml"
            written = await self.hass.async_add_executor_job(
                _write_if_changed,
                self.hass.config.path("esphome", filename),
                content,
            )
            if written:
                await self._compile(filename)
                await self._adopt(module)

    async def _compile(self, filename: str) -> None:
        session = async_get_clientsession(self.hass)
        explicit = (self.entry.data.get("dashboard_url") or "").strip() or None
        for base in dashboard_candidates(explicit):
            try:
                async with asyncio.timeout(3):
                    response = await session.get(f"{base}/version")
                    if response.status != 200:
                        continue
                socket = "wss://" if base.startswith("https://") else "ws://"
                host = base.split("://", 1)[1]
                async with session.ws_connect(f"{socket}{host}/ws", timeout=5) as ws:
                    await ws.send_json(compile_message(filename))
                _LOGGER.info("ESPHome kompilerer %s via %s", filename, base)
                return
            except Exception:
                _LOGGER.debug("ESPHome-dashboardet svarte ikke på %s", base, exc_info=True)
        _LOGGER.info(
            "Skrev %s. ESPHome-dashboardet svarte ikke, så kompilering startes i dashboardet.",
            filename,
        )

    async def _adopt(self, module: dict) -> None:
        host = f"{module['device_name']}.local"
        try:
            result = await self.hass.config_entries.flow.async_init(
                "esphome",
                context={"source": "user"},
                data={"host": host},
            )
        except Exception:
            _LOGGER.info("Kortet %s er ikke på nett ennå. Første flashing skjer over USB.", host)
            return
        if result.get("type") == "create_entry":
            return
        step = result.get("step_id") or ""
        if result.get("type") == "form" and not result.get("errors") and "encrypt" in step:
            key_name = _schema_key(result.get("data_schema"))
            if key_name:
                try:
                    await self.hass.config_entries.flow.async_configure(
                        result["flow_id"],
                        {key_name: module["api_key"]},
                    )
                    return
                except Exception:
                    _LOGGER.info("API-nøkkelen for %s ligger i HI-node til kortet er på nett.", host)
        flow_id = result.get("flow_id")
        if flow_id and result.get("type") != "abort":
            await self.hass.config_entries.flow.async_abort(flow_id)
        _LOGGER.info("Kortet %s kobles til ESPHome etter USB-flashing.", host)


def _profile(profile_id: str):
    if not profile_id:
        return None
    try:
        return profile_by_id(profile_id)
    except KeyError:
        return None


def _write_if_changed(path: str, content: str) -> bool:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    if current == content:
        return False
    target.write_text(content, encoding="utf-8")
    return True


def _events(raw: list):
    found = []
    for pair in raw:
        start = _stamp(pair[0])
        end = _stamp(pair[1])
        if start is not None and end is not None:
            found.append((start, end))
    return found


def _stamp(value):
    if not value:
        return None
    return dt_util.parse_datetime(value)


def _schema_key(schema):
    mapping = getattr(schema, "schema", None)
    if not isinstance(mapping, dict):
        return None
    for key in mapping:
        name = getattr(key, "schema", key)
        if isinstance(name, str):
            return name
    return None
