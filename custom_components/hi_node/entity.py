"""Felles enhet for hjelperne på anlegget."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN


class HiEntity(Entity):
    """Entitet som hører til ett anlegg. group sier hvilken boks den vises i."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime, unique_suffix: str, name: str, group: str | None = None) -> None:
        self.runtime = runtime
        self._group = group
        self._attr_unique_id = f"{runtime.entry.entry_id}_{unique_suffix}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.entry.entry_id)},
            name=runtime.entry.title,
            manufacturer="Hegland Innovations",
            model="HI-node",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.runtime.listen(self.async_write_ha_state))
