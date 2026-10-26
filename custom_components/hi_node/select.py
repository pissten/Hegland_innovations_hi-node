"""Varighet for nød-stenging av booking."""

from homeassistant.components.select import SelectEntity

from .availability import DEFAULT_DURATION_KEY, DURATION_OPTIONS
from .const import DOMAIN
from .entity import HiEntity

_OPTION_BY_KEY = {key: label for key, label in DURATION_OPTIONS}
_KEY_BY_LABEL = {label: key for key, label in DURATION_OPTIONS}


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AvailabilityDurationSelect(runtime)])


class AvailabilityDurationSelect(HiEntity, SelectEntity):
    """Hvor lenge booking skal være stengt når bryteren slås på."""

    def __init__(self, runtime) -> None:
        super().__init__(runtime, "availability_duration", "Stengevarighet", group="site")
        self._attr_options = [label for _, label in DURATION_OPTIONS]

    @property
    def current_option(self) -> str | None:
        key = str(self.runtime.data.get("availability_duration") or DEFAULT_DURATION_KEY)
        return _OPTION_BY_KEY.get(key, _OPTION_BY_KEY[DEFAULT_DURATION_KEY])

    async def async_select_option(self, option: str) -> None:
        key = _KEY_BY_LABEL.get(option)
        if key is None:
            return
        self.runtime.data["availability_duration"] = key
        if self.runtime.data.get("booking_unavailable"):
            await self.runtime.async_set_unavailable()
        else:
            await self.runtime.async_persist()
