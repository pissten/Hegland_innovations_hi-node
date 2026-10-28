"""Viser om skyen eller iCal styrer, og adressen booking skal poste til."""

from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.network import get_url
from homeassistant.util import dt as dt_util

from .availability import format_closed_until
from .brain import booking_event, oven_status
from .const import DOMAIN, ROLES
from .entity import HiEntity
from .features import binding, has_feature


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    entities = [ModeSensor(runtime), OvenStatus(runtime), ClosedUntilSensor(runtime)]
    if has_feature(runtime.normalized, "override_timers"):
        entities.extend(OverrideRemainingSensor(runtime, role) for role in ROLES)
    if has_feature(runtime.normalized, "climate") and binding(
        runtime.normalized, "climate_entity"
    ):
        entities.extend(
            [
                ClimateCurrentSensor(runtime),
                ClimateTargetSensor(runtime),
                ClimateLinkedSensor(runtime),
            ]
        )
    if runtime._harvia_available():
        entities.append(HarviaLastResetSensor(runtime))
        if binding(runtime.normalized, "remaining_time_entity"):
            entities.append(HarviaRemainingSensor(runtime))
    async_add_entities(entities)


class ModeSensor(HiEntity, SensorEntity):
    """webhook mens helsen svarer, ical etter tre bom."""

    def __init__(self, runtime) -> None:
        super().__init__(runtime, "mode", "Styring")

    @property
    def native_value(self):
        if self.runtime.decision is None:
            return "webhook"
        return self.runtime.decision.mode

    @property
    def extra_state_attributes(self):
        decision = self.runtime.decision
        return {
            "reason": None if decision is None else decision.reason,
            "webhook": _webhook_url(self.runtime),
            "failures": self.runtime.tracker.failures,
        }


class OvenStatus(HiEntity, SensorEntity):
    """Sier om ovnen skal kjøre på grunn av booking, frostvakt eller grunnvarme."""

    def __init__(self, runtime) -> None:
        super().__init__(runtime, "oven_status", "Status", group="oven")

    @property
    def native_value(self):
        decision = self.runtime.decision
        now = dt_util.now()
        if decision is None:
            return "Av"
        start = None
        duration_min = None
        if decision.reason == "booking":
            pre, post = self.runtime.data["margins"]["oven"]
            event = booking_event(
                now, _event_pairs(self.runtime.data.get("events")), int(pre), int(post)
            )
            if event is not None:
                start, end = event
                duration_min = max(1, int(round((end - start).total_seconds() / 60)))
        return oven_status(decision.reason, start, now, duration_min)


class ClosedUntilSensor(HiEntity, SensorEntity):
    """Når nød-stengingen opphører, eller Åpen."""

    def __init__(self, runtime) -> None:
        super().__init__(runtime, "closed_until", "Stengt til", group="site")

    @property
    def native_value(self):
        return format_closed_until(
            self.runtime.data.get("booking_unavailable_until"),
            dt_util.now(),
        )


class OverrideRemainingSensor(HiEntity, SensorEntity):
    """Hele minutter til en manuell overstyring utløper."""

    _attr_native_unit_of_measurement = "min"
    _attr_icon = "mdi:timer-outline"

    def __init__(self, runtime, role: str) -> None:
        names = {"oven": "Ovn", "door": "Dør", "light": "Lys"}
        super().__init__(
            runtime,
            f"override_remaining_{role}",
            f"Manuell {names[role].lower()} gjenstår",
            group=role,
        )
        self._role = role

    @property
    def native_value(self):
        return self.runtime.override_remaining_minutes(self._role)


class ClimateLinkedSensor(HiEntity, SensorEntity):
    """Viser entity_id for mappet climate."""

    _attr_icon = "mdi:thermostat"

    def __init__(self, runtime) -> None:
        super().__init__(runtime, "climate_entity", "Climate-enhet", group="climate")

    @property
    def native_value(self):
        return binding(self.runtime.normalized, "climate_entity") or "Ikke satt"


class ClimateCurrentSensor(HiEntity, SensorEntity):
    """Aktuell temperatur fra mappet climate."""

    _attr_native_unit_of_measurement = "°C"
    _attr_icon = "mdi:thermometer"

    def __init__(self, runtime) -> None:
        super().__init__(
            runtime, "climate_current", "Aktuell temperatur", group="climate"
        )

    @property
    def native_value(self):
        return self.runtime.climate_current_temperature()


class ClimateTargetSensor(HiEntity, SensorEntity):
    """Settpunkt fra mappet climate."""

    _attr_native_unit_of_measurement = "°C"
    _attr_icon = "mdi:thermometer-chevron-up"

    def __init__(self, runtime) -> None:
        super().__init__(
            runtime, "climate_target", "Settpunkt", group="climate"
        )

    @property
    def native_value(self):
        return self.runtime.climate_target_temperature()


class HarviaRemainingSensor(HiEntity, SensorEntity):
    """Speil av Harvia remaining_time (minutter når mulig)."""

    _attr_icon = "mdi:timer-sand"

    def __init__(self, runtime) -> None:
        super().__init__(
            runtime,
            "harvia_remaining",
            "Harvia gjenstår",
            group="harvia",
        )

    @property
    def native_value(self):
        minutes = self.runtime._harvia_remaining_minutes()
        if minutes is None:
            entity_id = binding(self.runtime.normalized, "remaining_time_entity")
            state = self.runtime.hass.states.get(entity_id) if entity_id else None
            return None if state is None else state.state
        hours, mins = divmod(int(minutes), 60)
        return f"{hours:02d}:{mins:02d}"

    @property
    def extra_state_attributes(self):
        return {
            "minutes": self.runtime._harvia_remaining_minutes(),
            "entity_id": binding(self.runtime.normalized, "remaining_time_entity"),
        }


class HarviaLastResetSensor(HiEntity, SensorEntity):
    """Siste fullførte Harvia dual-cycle."""

    _attr_icon = "mdi:history"

    def __init__(self, runtime) -> None:
        super().__init__(
            runtime,
            "harvia_last_reset",
            "Siste Harvia-reset",
            group="harvia",
        )

    @property
    def native_value(self):
        raw = self.runtime.data.get("last_reset")
        if not raw:
            return "Aldri"
        stamp = dt_util.parse_datetime(str(raw))
        if stamp is None:
            return str(raw)
        local = dt_util.as_local(stamp)
        return local.strftime("%d.%m.%Y %H:%M")

    @property
    def extra_state_attributes(self):
        remaining_entity = binding(
            self.runtime.normalized,
            "remaining_time_entity",
        )
        remaining_state = (
            self.runtime.hass.states.get(remaining_entity)
            if remaining_entity
            else None
        )
        return {
            "busy": bool(self.runtime.data.get("harvia_reset_busy")),
            "reason": self.runtime.data.get("harvia_last_reset_reason"),
            "oven_entity": self.runtime._oven_entity_id(),
            "power_entity": binding(
                self.runtime.normalized,
                "heater_power_entity",
            ),
            "remaining_entity": remaining_entity,
            "remaining": None if remaining_state is None else remaining_state.state,
            "iso": self.runtime.data.get("last_reset"),
        }


def _event_pairs(raw) -> list[tuple[datetime, datetime]]:
    found = []
    for pair in raw or []:
        try:
            start = datetime.fromisoformat(pair[0])
            end = datetime.fromisoformat(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        found.append((start, end))
    return found


def _webhook_url(runtime) -> str:
    path = f"/api/webhook/{runtime.webhook_id}"
    try:
        base = get_url(runtime.hass, allow_external=False, allow_internal=True)
    except Exception:
        return path
    return f"{base}{path}"
