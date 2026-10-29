"""Grunnvarme som egen kalender i Home Assistant."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import HiEntity
from .features import has_feature
from .grunnvarme_calendar import (
    DEFAULT_SUMMARY,
    calendar_active,
    create_event_record,
    delete_event_record,
    expand_events,
    update_event_record,
)


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    if not has_feature(runtime.normalized, "grunnvarme_schedule"):
        return
    async_add_entities([GrunnvarmeCalendar(runtime)])


class GrunnvarmeCalendar(HiEntity, CalendarEntity):
    """Kalender «Grunnvarme» — synlig og redigerbar i vanlig kalender-UI."""

    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
    )
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, runtime) -> None:
        super().__init__(
            runtime, "grunnvarme_calendar", "Grunnvarme", group="oven"
        )

    @property
    def event(self) -> CalendarEvent | None:
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
