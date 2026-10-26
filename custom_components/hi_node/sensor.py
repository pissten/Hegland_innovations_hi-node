"""Viser om skyen eller iCal styrer, og adressen booking skal poste til."""

from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.network import get_url
from homeassistant.util import dt as dt_util

from .availability import format_closed_until
from .brain import booking_event, oven_status
from .const import DOMAIN
from .entity import HiEntity


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ModeSensor(runtime), OvenStatus(runtime), ClosedUntilSensor(runtime)])


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
