"""Manuell overstyring, grunnvarme og frostvakt. De er lokale på noden."""

from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN
from .entity import HiEntity


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            FlagSwitch(runtime, "override_oven", "Manuell ovn", "overrides", "oven", "oven"),
            FlagSwitch(runtime, "override_door", "Manuell dør", "overrides", "door", "door"),
            FlagSwitch(runtime, "override_light", "Manuell lys", "overrides", "light", "light"),
            FlagSwitch(runtime, "grunnvarme", "Grunnvarme", "grunnvarme_timeplan", None, "oven"),
            FlagSwitch(runtime, "frostvakt", "Frostvakt", "frost_enabled", None, "oven"),
            BookingClosedSwitch(runtime),
        ]
    )


class FlagSwitch(HiEntity, SwitchEntity):
    """En lokal bryter som hjernen leser før den rører reléet."""

    def __init__(
        self, runtime, suffix: str, name: str, bucket: str, role: str | None, group: str
    ) -> None:
        super().__init__(runtime, suffix, name, group=group)
        self._bucket = bucket
        self._role = role

    @property
    def is_on(self) -> bool:
        if self._role is None:
            return bool(self.runtime.data.get(self._bucket))
        return bool(self.runtime.data[self._bucket].get(self._role))

    async def async_turn_on(self, **kwargs) -> None:
        self._set(True)
        await self.runtime.async_apply_now()

    async def async_turn_off(self, **kwargs) -> None:
        self._set(False)
        await self.runtime.async_apply_now()

    def _set(self, value: bool) -> None:
        if self._role is None:
            self.runtime.data[self._bucket] = value
        else:
            self.runtime.data[self._bucket][self._role] = value


class BookingClosedSwitch(HiEntity, SwitchEntity):
    """Stenger tilbudet for nye bookinger via booking-API."""

    def __init__(self, runtime) -> None:
        super().__init__(runtime, "booking_closed", "Booking stengt", group="site")

    @property
    def is_on(self) -> bool:
        return bool(self.runtime.data.get("booking_unavailable"))

    async def async_turn_on(self, **kwargs) -> None:
        await self.runtime.async_set_unavailable()

    async def async_turn_off(self, **kwargs) -> None:
        await self.runtime.async_clear_unavailable()
