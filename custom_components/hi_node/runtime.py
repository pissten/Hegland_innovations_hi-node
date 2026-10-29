"""Kjører booking-hjernen på noden og skriver ESPHome-oppsettet."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import datetime, timedelta
from pathlib import Path

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .brain import RoleState, decide, next_frost_calling, parse_command
from .calendar_feed import in_margin_window, parse_ical
from .climate_control import target_c_for_reason
from .const import DEFAULT_MARGINS, DOMAIN, RESET_HOLD_SECONDS, ROLES
from .harvia_reset import (
    automatic_reset_reason,
    parse_remaining_minutes,
    run_reset_cycle,
)
from .availability import (
    DEFAULT_DURATION_KEY,
    availability_url,
    duration_minutes_for,
    parse_availability_document,
)
from .margins import (
    apply_remote_margins,
    margin_payload,
    margin_sync_action,
    margins_url,
    parse_margin_document,
)
from .dashboard import compile_message, dashboard_candidates
from .features import binding, has_feature, normalize_entry_data, schedule_active
from .grunnvarme_calendar import (
    calendar_active,
    delete_event_record,
    ensure_seeded,
    update_event_record,
)
from .health import HealthTracker
from .profiles import profile_by_id, render_profile
from .runtime_logic import (
    expire_overrides,
    next_oven_mismatch,
    should_notify_alarm,
)

_LOGGER = logging.getLogger(__name__)


def _blank_state() -> dict:
    return {
        "commands": {role: False for role in ROLES},
        "overrides": {role: False for role in ROLES},
        "override_until": {role: None for role in ROLES},
        "override_minutes": 60,
        "margins": {role: [pre, post] for role, (pre, post) in DEFAULT_MARGINS.items()},
        "events": [],
        "failures": 0,
        "fallback": False,
        "last_failure": None,
        "grunnvarme_timeplan": False,
        "grunnvarme_calendar": [],
        "grunnvarme_hours_per_day": 0,
        "grunnvarme_hours_today": 0,
        "grunnvarme_day": None,
        "grunnvarme_mark": None,
        "frost_enabled": False,
        "frost_calling": False,
        "frost_c": 20,
        "frost_hysteresis_c": 1,
        "frost_off_c": 40,
        "oven_on_since": None,
        "reset_hold_until": None,
        "harvia_reset_busy": False,
        "last_reset": None,
        "harvia_last_reset_reason": None,
        "harvia_remaining_low_handled": False,
        "harvia_power_off_handled": False,
        "alarm_delay_seconds": 45,
        "mismatch_since": None,
        "oven_mismatch": False,
        "margins_seen_at": None,
        "margins_seeded": False,
        "margins_dirty": False,
        "booking_unavailable": False,
        "booking_unavailable_until": None,
        "booking_unavailable_starts": None,
        "availability_duration": DEFAULT_DURATION_KEY,
    }


class HiNodeRuntime:
    """Én oppføring, ett anlegg."""

    def __init__(self, hass, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.normalized = normalize_entry_data(dict(entry.data))
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.data = _blank_state()
        self.tracker = HealthTracker()
        self.decision = None
        self.webhook_id = f"{DOMAIN}_{entry.entry_id}"
        self._listeners: list = []
        self._unsubs: list = []
        self._margin_lock = asyncio.Lock()
        self._harvia_lock = asyncio.Lock()
        self._recent_switch_writes: dict[str, tuple[str, datetime]] = {}
        self._margin_missing_logged = False
        self._availability_missing_logged = False

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
        return list(self.normalized.get("modules") or [])

    async def async_drop_group_devices(self) -> None:
        """Fjern ovn, dør og lys som egne enheter etter at entitetene er flyttet tilbake."""
        tasks = [task for task in list(getattr(self.entry, "_tasks", ())) if not task.done()]
        if tasks:
            await asyncio.wait(tasks)
        from homeassistant.helpers import device_registry as dr

        registry = dr.async_get(self.hass)
        for group in ("oven", "door", "light"):
            child = registry.async_get_child_device_by_identifier(
                (DOMAIN, f"{self.entry.entry_id}_{group}"),
                self.entry.entry_id,
            )
            if child is not None:
                registry.async_remove_device(child.id)

    async def async_start(self) -> None:
        self.normalized = normalize_entry_data(dict(self.entry.data))
        stored = await self.store.async_load()
        self.data = _blank_state()
        if stored:
            self.data.update(stored)
            self.data["commands"] = {**_blank_state()["commands"], **(stored.get("commands") or {})}
            self.data["overrides"] = {
                **_blank_state()["overrides"],
                **(stored.get("overrides") or {}),
            }
            self.data["override_until"] = {
                **_blank_state()["override_until"],
                **(stored.get("override_until") or {}),
            }
            self.data["margins"] = {**_blank_state()["margins"], **(stored.get("margins") or {})}
        stored = stored or {}
        for key, value in self.normalized["runtime"].items():
            if key not in stored:
                self.data[key] = value
        self.data["harvia_reset_busy"] = False
        entry_temps = self.entry.data.get("temps")
        if has_feature(self.normalized, "climate"):
            for key in ("booking_c", "grunnvarme_c", "default_c"):
                self.data[key] = self.normalized["temps"][key]
        if has_feature(self.normalized, "frost") and isinstance(entry_temps, dict):
            for key in ("frost_c", "frost_hysteresis_c", "frost_off_c"):
                self.data[key] = self.normalized["temps"][key]
        if has_feature(self.normalized, "grunnvarme_schedule"):
            seeded = ensure_seeded(
                self.data.get("grunnvarme_calendar"),
                self.normalized.get("schedule"),
                dt_util.now(),
            )
            if seeded != list(self.data.get("grunnvarme_calendar") or []):
                self.data["grunnvarme_calendar"] = seeded
                await self.store.async_save(self.data)
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
        harvia_entities = self._harvia_watch_entities()
        if harvia_entities:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    harvia_entities,
                    self._harvia_state_changed,
                )
            )
        role_entities = list(self._role_entities())
        if has_feature(self.normalized, "override_timers") and role_entities:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    role_entities,
                    self._physical_state_changed,
                )
            )
        await self._tick(dt_util.now())

    async def async_stop(self) -> None:
        webhook.async_unregister(self.hass, self.webhook_id)
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def async_apply_now(self) -> None:
        await self._apply(dt_util.now())

    async def async_set_override(self, role: str, enabled: bool) -> None:
        """Sett lokal overstyring og oppdater tidsfristen."""
        if role not in ROLES:
            raise ValueError(f"Ukjent rolle: {role}")
        self.data["overrides"][role] = bool(enabled)
        if has_feature(self.normalized, "override_timers") and enabled:
            self._start_override_timer(role, dt_util.now())
        else:
            self.data["override_until"][role] = None
        await self.async_apply_now()

    def override_remaining_minutes(self, role: str, now=None) -> int | None:
        """Returner hele minutter igjen, eller None uten aktiv tidsfrist."""
        deadline = _stamp(self.data.get("override_until", {}).get(role))
        if deadline is None:
            return None
        current = dt_util.as_local(now or dt_util.now())
        return max(0, int(math.ceil((deadline - current).total_seconds() / 60)))

    async def async_reset_harvia_now(self) -> bool:
        """Kjør manuell Harvia-reset når modulen og begge bryterne finnes."""
        if not self._harvia_available():
            return False
        now = dt_util.now()
        completed = await self._run_harvia_reset(now, "manual")
        if completed:
            await self._apply(now)
        else:
            await self.store.async_save(self.data)
            self._notify()
        return completed

    async def async_persist(self) -> None:
        """Lagre lokal tilstand uten ny beslutning."""
        await self.store.async_save(self.data)
        self._notify()

    async def async_set_temp(self, key: str, value: float) -> None:
        """Oppdater arbeidskopi og config entry for ett temperatursettpunkt."""
        if key not in ("booking_c", "grunnvarme_c", "default_c"):
            raise ValueError(f"Ukjent temperatursettpunkt: {key}")
        number = float(value)
        self.data[key] = number
        entry_data = dict(self.entry.data)
        entry_temps = dict(entry_data.get("temps") or {})
        entry_temps[key] = number
        entry_data["temps"] = entry_temps
        self.hass.config_entries.async_update_entry(self.entry, data=entry_data)
        self.normalized = normalize_entry_data(entry_data)
        await self.async_apply_now()

    async def async_push_margins(self) -> None:
        """Lokal endring av før/etter sendes til booking med en gang."""
        async with self._margin_lock:
            await self._push_margins()

    def _apply_availability(self, document: dict) -> None:
        parsed = parse_availability_document(document)
        self.data["booking_unavailable"] = bool(parsed["active"])
        self.data["booking_unavailable_until"] = parsed["ends_at"] if parsed["active"] else None
        self.data["booking_unavailable_starts"] = parsed["starts_at"] if parsed["active"] else None

    async def async_refresh_availability(self) -> None:
        """Hent aktiv nød-stenging fra booking."""
        document = await self._request_availability("get")
        if document is None:
            return
        self._apply_availability(document)

    async def async_set_unavailable(self, duration_minutes: int | None = None) -> bool:
        """Sett badstuen utilgjengelig for booking."""
        now = dt_util.now()
        if duration_minutes is None:
            duration_minutes = duration_minutes_for(self.data.get("availability_duration"), now)
        document = await self._request_availability(
            "put", {"durationMinutes": int(duration_minutes)}
        )
        if document is None:
            _LOGGER.warning("Klarte ikke å stenge booking via /node/availability")
            return False
        self._apply_availability(document)
        self._notify()
        return True

    async def async_clear_unavailable(self) -> bool:
        """Fjern aktiv nød-stenging med en gang."""
        document = await self._request_availability("delete")
        if document is None:
            _LOGGER.warning("Klarte ikke å åpne booking via /node/availability")
            return False
        self._apply_availability(document)
        self._notify()
        return True

    async def _request_availability(self, method: str, payload: dict | None = None):
        url = availability_url(self.entry.data.get("ical_url"))
        if not url:
            return None
        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(10):
                if method == "put":
                    response = await session.put(url, json=payload)
                elif method == "delete":
                    response = await session.delete(url)
                else:
                    response = await session.get(url)
                text = await response.text()
                if response.status == 404 and not self._availability_missing_logged:
                    _LOGGER.warning(
                        "Booking har ikke /node/availability ennå. Bygg booking på nytt."
                    )
                    self._availability_missing_logged = True
                if response.status >= 300:
                    return None
                if not text:
                    return {"active": False}
                return json.loads(text)
        except Exception:
            _LOGGER.debug("Klarte ikke å synke tilgjengelighet", exc_info=True)
            return None

    async def _sync_margins(self) -> None:
        try:
            async with self._margin_lock:
                seeded = bool(self.data.get("margins_seeded"))
                dirty = bool(self.data.get("margins_dirty"))
                if margin_sync_action(
                    seeded=seeded,
                    dirty=dirty,
                    seen_at=self.data.get("margins_seen_at"),
                    remote_at=None,
                ) == "push":
                    await self._push_margins()
                    return
                document = await self._request_margins("get")
                if document is None:
                    return
                stamp, remote = parse_margin_document(document)
                action = margin_sync_action(
                    seeded=True,
                    dirty=False,
                    seen_at=self.data.get("margins_seen_at"),
                    remote_at=stamp,
                )
                if action != "pull":
                    return
                apply_remote_margins(self.data["margins"], remote)
                self.data["margins_seen_at"] = stamp
                self.data["margins_dirty"] = False
        except Exception:
            _LOGGER.debug("Marginsynk feilet", exc_info=True)

    async def _push_margins(self) -> None:
        document = await self._request_margins("put", {"margins": margin_payload(self.data["margins"])})
        if document is None:
            return
        stamp, remote = parse_margin_document(document)
        if not stamp:
            return
        apply_remote_margins(self.data["margins"], remote)
        self.data["margins_seen_at"] = stamp
        self.data["margins_seeded"] = True
        self.data["margins_dirty"] = False

    async def _request_margins(self, method: str, payload: dict | None = None):
        url = margins_url(self.entry.data.get("ical_url"))
        if not url:
            return None
        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(10):
                if method == "put":
                    response = await session.put(url, json=payload)
                else:
                    response = await session.get(url)
                if response.status == 404 and not self._margin_missing_logged:
                    _LOGGER.warning("Booking har ikke /node/margins ennå. Bygg booking på nytt.")
                    self._margin_missing_logged = True
                if response.status >= 300:
                    return None
                return json.loads(await response.text())
        except Exception:
            _LOGGER.debug("Klarte ikke å synke marginer", exc_info=True)
            return None

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
        if ok:
            await self._sync_margins()
            await self.async_refresh_availability()
        await self._apply(now)

    async def _ical_tick(self, now) -> None:
        await self._refresh_ical()
        await self._apply(dt_util.as_local(now))

    async def _harvia_state_changed(self, event) -> None:
        """Reager med en gang på Harvia-strøm og gjenstående tid."""
        await self._apply(dt_util.now())

    async def _physical_state_changed(self, event) -> None:
        """Start overstyring når et menneske bruker en bundet bryter."""
        context = getattr(event, "context", None)
        if not getattr(context, "user_id", None):
            return
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if (
            not entity_id
            or new_state is None
            or new_state.state not in ("on", "off")
            or (old_state is not None and old_state.state == new_state.state)
        ):
            return
        expected = self._recent_switch_writes.get(entity_id)
        now = dt_util.now()
        if expected is not None:
            expected_state, expires = expected
            if now <= expires and new_state.state == expected_state:
                return
            self._recent_switch_writes.pop(entity_id, None)
        role = self._role_entities().get(entity_id)
        if role is None:
            return
        self.data["overrides"][role] = True
        self._start_override_timer(role, now)
        await self._apply(now)

    def _start_override_timer(self, role: str, now) -> None:
        minutes = max(0.0, float(self.data.get("override_minutes") or 0))
        self.data["override_until"][role] = (
            dt_util.as_local(now) + timedelta(minutes=minutes)
        ).isoformat()

    def _expire_override_timers(self, now) -> None:
        if not has_feature(self.normalized, "override_timers"):
            return
        overrides, deadlines, _changed = expire_overrides(
            self.data["overrides"],
            self.data["override_until"],
            now,
        )
        self.data["overrides"] = overrides
        self.data["override_until"] = deadlines

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

    def grunnvarme_calendar_events(self) -> list:
        events = self.data.get("grunnvarme_calendar")
        return list(events) if isinstance(events, list) else []

    def _grunnvarme_in_schedule(self, now) -> bool:
        events = self.grunnvarme_calendar_events()
        if events:
            return calendar_active(events, now)
        return schedule_active(self.normalized.get("schedule"), now)

    async def async_grunnvarme_calendar_create(self, record: dict) -> None:
        events = self.grunnvarme_calendar_events()
        events.append(record)
        self.data["grunnvarme_calendar"] = events
        await self.store.async_save(self.data)
        await self.async_apply_now()
        self._notify()

    async def async_grunnvarme_calendar_update(self, uid: str, **kwargs) -> None:
        self.data["grunnvarme_calendar"] = update_event_record(
            self.grunnvarme_calendar_events(), uid, **kwargs
        )
        await self.store.async_save(self.data)
        await self.async_apply_now()
        self._notify()

    async def async_grunnvarme_calendar_delete(self, uid: str) -> None:
        self.data["grunnvarme_calendar"] = delete_event_record(
            self.grunnvarme_calendar_events(), uid
        )
        await self.store.async_save(self.data)
        await self.async_apply_now()
        self._notify()

    def role_state(self, now):
        margins = {
            role: tuple(self.data["margins"].get(role) or DEFAULT_MARGINS[role])
            for role in ROLES
        }
        schedule_enabled = (
            bool(self.data.get("grunnvarme_timeplan"))
            if has_feature(self.normalized, "grunnvarme_schedule")
            else None
        )
        return RoleState(
            fallback=self.tracker.fallback,
            commands=dict(self.data["commands"]),
            events=_events(self.data.get("events") or []),
            overrides=dict(self.data["overrides"]),
            margins=margins,
            grunnvarme_timeplan=bool(self.data.get("grunnvarme_timeplan")),
            grunnvarme_schedule_enabled=schedule_enabled,
            grunnvarme_in_schedule=(
                self._grunnvarme_in_schedule(now)
                if schedule_enabled is not None
                else False
            ),
            grunnvarme_hours_per_day=float(self.data.get("grunnvarme_hours_per_day") or 0),
            grunnvarme_hours_today=float(self.data.get("grunnvarme_hours_today") or 0),
            frost_enabled=bool(self.data.get("frost_enabled")),
            frost_calling=bool(self.data.get("frost_calling")),
            frost_c=float(self.data.get("frost_c") or 20),
            temperature_c=self._temperature(),
            oven_on_since=_stamp(self.data.get("oven_on_since")),
            reset_hold_until=_stamp(self.data.get("reset_hold_until")),
        )

    def _temperature(self):
        climate_entity = binding(self.normalized, "climate_entity")
        if climate_entity:
            state = self.hass.states.get(climate_entity)
            if state is None:
                return None
            return _temperature_value(state.attributes.get("current_temperature"))

        entity_id = (
            binding(self.normalized, "temperature_entity")
            or self.entry.data.get("temperature_entity")
        )
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", "none", ""):
            return None
        return _temperature_value(state.state)

    def _update_frost_calling(self) -> None:
        temps = self.normalized["temps"]
        self.data["frost_calling"] = next_frost_calling(
            previous=bool(self.data.get("frost_calling")),
            feature_enabled=has_feature(self.normalized, "frost"),
            switch_enabled=bool(self.data.get("frost_enabled")),
            temperature_c=self._temperature(),
            frost_c=float(self.data.get("frost_c", temps["frost_c"])),
            hysteresis_c=float(
                self.data.get("frost_hysteresis_c", temps["frost_hysteresis_c"])
            ),
            frost_off_c=float(
                self.data.get("frost_off_c", temps["frost_off_c"])
            ),
        )

    async def _apply(self, now) -> None:
        if self.data.get("harvia_reset_busy"):
            return
        now = dt_util.as_local(now)
        self._expire_override_timers(now)
        hold = _stamp(self.data.get("reset_hold_until"))
        if hold is not None and now >= hold:
            self.data["reset_hold_until"] = None
        self._update_frost_calling()
        state = self.role_state(now)
        decision = decide(state, now)
        if self._harvia_available():
            remaining_minutes = self._harvia_remaining_minutes()
            power_is_on = self._switch_state(
                binding(self.normalized, "heater_power_entity")
            )
            self._refresh_harvia_latches(remaining_minutes, power_is_on)
            heater_limit_reached = (
                decision.reason == "heater_12h"
                and state.oven_on_since is not None
            )
            pre, post = state.margins.get("oven") or (90, 0)
            in_booking = in_margin_window(
                now,
                state.events,
                int(pre),
                int(post),
            )
            reset_reason = automatic_reset_reason(
                feature_enabled=True,
                oven_desired=bool(decision.oven or heater_limit_reached),
                heater_limit_reached=heater_limit_reached,
                remaining_minutes=remaining_minutes,
                power_is_on=power_is_on,
                remaining_low_handled=bool(
                    self.data.get("harvia_remaining_low_handled")
                ),
                power_off_handled=bool(
                    self.data.get("harvia_power_off_handled")
                ),
                in_booking=in_booking,
            )
            if reset_reason and await self._run_harvia_reset(now, reset_reason):
                state = self.role_state(now)
                decision = decide(state, now)
        elif decision.reason == "heater_12h" and state.oven_on_since is not None:
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
        await self._update_oven_mismatch(decision, now)
        for module in self.modules():
            for role, entity_id in (module.get("roles") or {}).items():
                if role in ROLES and entity_id:
                    await self._set_switch(entity_id, bool(getattr(decision, role)))
        await self._set_climate_temperature(decision.reason)
        await self.store.async_save(self.data)
        self._notify()

    def _harvia_available(self) -> bool:
        return bool(
            has_feature(self.normalized, "harvia_12h")
            and binding(self.normalized, "heater_power_entity")
            and self._oven_entity_id()
        )

    def _harvia_watch_entities(self) -> list[str]:
        if not self._harvia_available():
            return []
        return list(
            dict.fromkeys(
                entity_id
                for entity_id in (
                    binding(self.normalized, "heater_power_entity"),
                    binding(self.normalized, "remaining_time_entity"),
                )
                if entity_id
            )
        )

    def _role_entities(self) -> dict[str, str]:
        found: dict[str, str] = {}
        for module in self.modules():
            for role, entity_id in (module.get("roles") or {}).items():
                if role in ROLES and entity_id:
                    found[entity_id] = role
        return found

    def _oven_entity_id(self) -> str | None:
        for module in self.modules():
            entity_id = (module.get("roles") or {}).get("oven")
            if entity_id:
                return entity_id
        return None

    def _harvia_remaining_minutes(self) -> int | None:
        entity_id = binding(self.normalized, "remaining_time_entity")
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        return None if state is None else parse_remaining_minutes(state.state)

    def _switch_state(self, entity_id: str | None) -> bool | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        if state.state == "on":
            return True
        if state.state == "off":
            return False
        return None

    async def _update_oven_mismatch(self, decision, now) -> None:
        previous = bool(self.data.get("oven_mismatch"))
        if not has_feature(self.normalized, "runtime_alarm"):
            self.data["mismatch_since"] = None
            self.data["oven_mismatch"] = False
            return
        power_on = (
            self._switch_state(binding(self.normalized, "heater_power_entity"))
            if self._harvia_available()
            else None
        )
        since, alarm = next_oven_mismatch(
            self.data.get("mismatch_since"),
            desired_on=bool(decision.oven),
            oven_on=self._switch_state(self._oven_entity_id()),
            power_on=power_on,
            now=now,
            delay_seconds=float(self.data.get("alarm_delay_seconds") or 0),
        )
        self.data["mismatch_since"] = since
        self.data["oven_mismatch"] = alarm
        if (
            should_notify_alarm(previous, alarm)
            and has_feature(self.normalized, "runtime_notify")
        ):
            await self._send_alarm_notification()

    async def _send_alarm_notification(self) -> None:
        entity_id = binding(self.normalized, "notify_entity")
        if not entity_id or not entity_id.startswith("notify."):
            return
        try:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {
                    "entity_id": entity_id,
                    "title": f"HI-node: {self.entry.title}",
                    "message": "Ovnen skal være på, men ovnsutgangen svarer ikke.",
                },
                blocking=False,
            )
        except Exception:
            _LOGGER.exception("Klarte ikke å sende ovnsavvik via %s", entity_id)

    def _refresh_harvia_latches(
        self,
        remaining_minutes: int | None,
        power_is_on: bool | None,
    ) -> None:
        if remaining_minutes is None or remaining_minutes > 5:
            self.data["harvia_remaining_low_handled"] = False
        if power_is_on is True:
            self.data["harvia_power_off_handled"] = False

    async def _run_harvia_reset(self, now, reason: str) -> bool:
        if self._harvia_lock.locked():
            return False
        oven_entity_id = self._oven_entity_id()
        power_entity_id = binding(self.normalized, "heater_power_entity")
        if not oven_entity_id or not power_entity_id:
            return False
        async with self._harvia_lock:
            self.data["harvia_reset_busy"] = True
            self._notify()
            try:
                await run_reset_cycle(
                    self.hass,
                    oven_entity_id,
                    power_entity_id,
                )
            except Exception:
                _LOGGER.exception("Harvia 12t-reset feilet (%s)", reason)
                return False
            finally:
                self.data["harvia_reset_busy"] = False
                self._notify()
            self.data["last_reset"] = now.isoformat()
            self.data["harvia_last_reset_reason"] = reason
            self.data["harvia_remaining_low_handled"] = True
            self.data["harvia_power_off_handled"] = True
            self.data["oven_on_since"] = now.isoformat()
            _LOGGER.info("Harvia 12t-reset fullført (%s)", reason)
            return True

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
        self._recent_switch_writes[entity_id] = (
            desired,
            dt_util.now() + timedelta(seconds=2),
        )
        await self.hass.services.async_call(
            "switch",
            service,
            {"entity_id": entity_id},
            blocking=False,
        )

    def climate_current_temperature(self) -> float | None:
        entity_id = binding(self.normalized, "climate_entity")
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        return _temperature_value(state.attributes.get("current_temperature"))

    def climate_target_temperature(self) -> float | None:
        entity_id = binding(self.normalized, "climate_entity")
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        return _temperature_value(state.attributes.get("temperature"))

    async def _set_climate_temperature(self, reason: str) -> None:
        if not has_feature(self.normalized, "climate"):
            return
        entity_id = binding(self.normalized, "climate_entity")
        if not entity_id:
            return
        current = self.hass.states.get(entity_id)
        if current is None or current.state in ("unknown", "unavailable"):
            return
        temps = {
            key: self.data.get(key, self.normalized["temps"][key])
            for key in ("booking_c", "grunnvarme_c", "default_c")
        }
        target = target_c_for_reason(reason, temps)
        current_target = _temperature_value(current.attributes.get("temperature"))
        if current_target is not None and abs(current_target - target) < 0.01:
            return
        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": target},
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


def _temperature_value(value):
    if value is None or str(value).lower() in ("unknown", "unavailable", "none", ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _schema_key(schema):
    mapping = getattr(schema, "schema", None)
    if not isinstance(mapping, dict):
        return None
    for key in mapping:
        name = getattr(key, "schema", key)
        if isinstance(name, str):
            return name
    return None
