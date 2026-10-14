"""Viser om skyen eller iCal styrer, og adressen booking skal poste til."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.network import get_url

from .const import DOMAIN
from .entity import HiEntity


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ModeSensor(runtime)])


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


def _webhook_url(runtime) -> str:
    path = f"/api/webhook/{runtime.webhook_id}"
    try:
        base = get_url(runtime.hass, allow_external=False, allow_internal=True)
    except Exception:
        return path
    return f"{base}{path}"
