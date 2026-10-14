"""Viser om booking svarer, og hva hjernen vil med ovn, dør og lys."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .const import DOMAIN
from .entity import HiEntity


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            BookingOnline(runtime),
            Desired(runtime, "oven", "Ovn skal kjøre"),
            Desired(runtime, "door", "Dør skal være åpen"),
            Desired(runtime, "light", "Lys skal være på"),
        ]
    )


class BookingOnline(HiEntity, BinarySensorEntity):
    """På når GET /health svarer. Av etter tre bom."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, runtime) -> None:
        super().__init__(runtime, "booking_online", "Booking svarer")

    @property
    def is_on(self) -> bool:
        return not self.runtime.tracker.fallback


class Desired(HiEntity, BinarySensorEntity):
    """Ønsket tilstand etter webhook, iCal og de lokale sikringene."""

    def __init__(self, runtime, role: str, name: str) -> None:
        super().__init__(runtime, f"desired_{role}", name)
        self._role = role

    @property
    def is_on(self) -> bool:
        decision = self.runtime.decision
        if decision is None:
            return False
        return bool(getattr(decision, self._role))

    @property
    def extra_state_attributes(self):
        decision = self.runtime.decision
        if decision is None:
            return {}
        return {"reason": decision.reason, "mode": decision.mode}
