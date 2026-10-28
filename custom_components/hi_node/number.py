"""Marginer og temperaturgrense. Samme tall som på Væmt når anlegget opprettes."""

from homeassistant.components.number import NumberEntity, NumberMode

from .const import DOMAIN, ROLES
from .entity import HiEntity
from .features import has_feature

_MARGIN_NAMES = {
    ("oven", 0): ("Ovn før", 180),
    ("oven", 1): ("Ovn etter", 180),
    ("door", 0): ("Dør før", 60),
    ("door", 1): ("Dør etter", 60),
    ("light", 0): ("Lys før", 60),
    ("light", 1): ("Lys etter", 60),
}


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for role in ROLES:
        for index in (0, 1):
            name, limit = _MARGIN_NAMES[(role, index)]
            entities.append(MarginNumber(runtime, role, index, name, limit))
    if has_feature(runtime.normalized, "climate"):
        entities.extend(
            [
                PlainNumber(
                    runtime,
                    "booking_c",
                    "Booking temperatur",
                    5,
                    120,
                    1,
                    "°C",
                    "oven",
                    persist_temp=True,
                ),
                PlainNumber(
                    runtime,
                    "grunnvarme_c",
                    "Grunnvarme temperatur",
                    5,
                    120,
                    1,
                    "°C",
                    "oven",
                    persist_temp=True,
                ),
                PlainNumber(
                    runtime,
                    "default_c",
                    "Standard temperatur",
                    5,
                    120,
                    1,
                    "°C",
                    "oven",
                    persist_temp=True,
                ),
            ]
        )
    if has_feature(runtime.normalized, "frost"):
        entities.extend(
            [
                PlainNumber(
                    runtime,
                    "frost_c",
                    "Frostvakt temperatur",
                    5,
                    30,
                    0.5,
                    "°C",
                    "oven",
                ),
                PlainNumber(
                    runtime,
                    "frost_hysteresis_c",
                    "Frostvakt hysterese",
                    0,
                    10,
                    0.5,
                    "°C",
                    "oven",
                ),
                PlainNumber(
                    runtime,
                    "frost_off_c",
                    "Frostvakt av-temperatur",
                    5,
                    60,
                    0.5,
                    "°C",
                    "oven",
                ),
            ]
        )
    if has_feature(runtime.normalized, "grunnvarme_quota"):
        entities.append(
            PlainNumber(
                runtime,
                "grunnvarme_hours_per_day",
                "Grunnvarme timer per dag",
                0,
                24,
                0.5,
                "h",
                "oven",
            )
        )
    async_add_entities(entities)


class MarginNumber(HiEntity, NumberEntity):
    """Minutter før eller etter en booking."""

    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _attr_native_min_value = 0
    _attr_native_unit_of_measurement = "min"

    def __init__(self, runtime, role: str, index: int, name: str, limit: int) -> None:
        side = "pre" if index == 0 else "post"
        super().__init__(runtime, f"margin_{role}_{side}", name, group=role)
        self._role = role
        self._index = index
        self._attr_native_max_value = limit

    @property
    def native_value(self):
        return self.runtime.data["margins"][self._role][self._index]

    async def async_set_native_value(self, value: float) -> None:
        current = list(self.runtime.data["margins"][self._role])
        current[self._index] = int(value)
        self.runtime.data["margins"][self._role] = current
        self.runtime.data["margins_dirty"] = True
        await self.runtime.async_push_margins()
        await self.runtime.async_apply_now()


class PlainNumber(HiEntity, NumberEntity):
    """Ett tall som ligger rett i lageret."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        runtime,
        key: str,
        name: str,
        low: float,
        high: float,
        step: float,
        unit: str,
        group: str,
        *,
        persist_temp: bool = False,
    ) -> None:
        super().__init__(runtime, key, name, group=group)
        self._key = key
        self._persist_temp = persist_temp
        self._attr_native_min_value = low
        self._attr_native_max_value = high
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self):
        return self.runtime.data.get(self._key)

    async def async_set_native_value(self, value: float) -> None:
        if self._persist_temp:
            await self.runtime.async_set_temp(self._key, value)
            return
        self.runtime.data[self._key] = float(value)
        await self.runtime.async_apply_now()
