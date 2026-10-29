"""Grunnvarme som egen kalender i Home Assistant."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .features import has_feature
from .grunnvarme_calendar import (
    DEFAULT_SUMMARY,
    calendar_active,
    create_event_record,
    expand_events,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    if not has_feature(runtime.normalized, "grunnvarme_schedule"):
        return
    entity = GrunnvarmeCalendar(runtime)
    async_add_entities([entity])
    _LOGGER.info("HI-node grunnvarme-kalender registrert for %s", entry.title)


class GrunnvarmeCalendar(CalendarEntity):
    """Kalender «Grunnvarme» — synlig og redigerbar i vanlig kalender-UI."""

    _attr_has_entity_name = True
    _attr_name = "Grunnvarme"
    _attr_icon = "mdi:calendar-clock"
    _attr_should_poll = False
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
    )

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.entry.entry_id}_grunnvarme_calendar"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.entry.entry_id)},
            name=runtime.entry.title,
            manufacturer="Hegland Innovations",
            model="HI-node",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.runtime.listen(self.async_write_ha_state))
        _LOGGER.info("HI-node kalender lagt til som %s", self.entity_id)

    @property
    def event(self) -> CalendarEvent | None:
        try:
            now = dt_util.now()
            items = expand_events(
                self.runtime.grunnvarme_calendar_events(),
                now,
                now + timedelta(days=14),
            )
            if not items:
                return None
            item = items[0]
            return CalendarEvent(
                start=item["start"],
                end=item["end"],
                summary=item["summary"],
                description=item.get("description"),
                uid=item["uid"],
                rrule=item.get("rrule"),
                recurrence_id=item.get("recurrence_id"),
            )
        except Exception:
            _LOGGER.exception("Kunne ikke beregne neste grunnvarme-hendelse")
            return None

    @property
    def extra_state_attributes(self):
        now = dt_util.now()
        return {
            "active_now": calendar_active(
                self.runtime.grunnvarme_calendar_events(), now
            ),
            "event_count": len(self.runtime.grunnvarme_calendar_events()),
        }

    async def async_get_events(
        self, hass, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        items = expand_events(
            self.runtime.grunnvarme_calendar_events(), start_date, end_date
        )
        return [
            CalendarEvent(
                start=item["start"],
                end=item["end"],
                summary=item["summary"] or DEFAULT_SUMMARY,
                description=item.get("description"),
                uid=item["uid"],
                rrule=item.get("rrule"),
                recurrence_id=item.get("recurrence_id"),
            )
            for item in items
        ]

    async def async_create_event(self, **kwargs) -> None:
        await self.runtime.async_grunnvarme_calendar_create(
            create_event_record(**kwargs)
        )
        self.async_write_ha_state()

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        del recurrence_id, recurrence_range
        await self.runtime.async_grunnvarme_calendar_delete(uid)
        self.async_write_ha_state()

    async def async_update_event(
        self,
        uid: str,
        event: dict,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        del recurrence_id, recurrence_range
        await self.runtime.async_grunnvarme_calendar_update(uid, **event)
        self.async_write_ha_state()
