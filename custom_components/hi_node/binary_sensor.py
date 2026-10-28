"""Viser om booking svarer, og hva hjernen vil med ovn, dør og lys."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import HiEntity
from .features import has_feature


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    entities = [
        BookingOnline(runtime),
        Desired(runtime, "oven", "Skal kjøre"),
        Desired(runtime, "door", "Skal være åpen"),
        Desired(runtime, "light", "Skal være på"),
    ]
    if has_feature(runtime.normalized, "grunnvarme_schedule"):
        entities.append(GrunnvarmeScheduleActive(runtime))
    async_add_entities(entities)


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
        super().__init__(runtime, f"desired_{role}", name, group=role)
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


class GrunnvarmeScheduleActive(HiEntity, BinarySensorEntity):
    """På når timeplanbryteren er aktiv og klokkevinduet gjelder."""

    def __init__(self, runtime) -> None:
        super().__init__(
            runtime,
            "grunnvarme_schedule_active",
            "Timeplan aktiv nå",
            group="oven",
        )

    @property
    def is_on(self) -> bool:
        state = self.runtime.role_state(dt_util.now())
        return bool(
            state.grunnvarme_schedule_enabled
            and state.grunnvarme_in_schedule
        )
