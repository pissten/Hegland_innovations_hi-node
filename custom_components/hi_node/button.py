"""Manuell knapp for Harvia sin dual-cycle."""

from homeassistant.components.button import ButtonEntity

from .const import DOMAIN
from .entity import HiEntity


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    if runtime._harvia_available():
        async_add_entities([HarviaResetButton(runtime)])


class HarviaResetButton(HiEntity, ButtonEntity):
    """Nullstill Harvia sin interne 12-timer."""

    _attr_icon = "mdi:restart"

    def __init__(self, runtime) -> None:
        super().__init__(
            runtime,
            "harvia_reset",
            "Nullstill Harvia 12t",
            group="harvia",
        )

    async def async_press(self) -> None:
        await self.runtime.async_reset_harvia_now()
