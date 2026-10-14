"""Les siste iCal-feed og avgjør om et tidspunkt ligger i marginen."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def parse_ical(text: str) -> list[tuple[datetime, datetime]]:
    """Hent start og slutt fra hvert VEVENT."""
    lines: list[str] = []
    for raw in text.splitlines():
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw.strip())

    events: list[tuple[datetime, datetime]] = []
    inside = False
    start: datetime | None = None
    end: datetime | None = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            inside = True
            start = None
            end = None
        elif line == "END:VEVENT":
            if start is not None and end is not None:
                events.append((start, end))
            inside = False
        elif inside and line.startswith("DTSTART"):
            start = _parse_stamp(line)
        elif inside and line.startswith("DTEND"):
            end = _parse_stamp(line)
    return events


def in_margin_window(
    now: datetime,
    events: list[tuple[datetime, datetime]],
    pre_min: int,
    post_min: int,
) -> bool:
    """True når now ligger mellom start minus pre og slutt pluss post."""
    pre = timedelta(minutes=pre_min)
    post = timedelta(minutes=post_min)
    for start, end in events:
        if start - pre <= now <= end + post:
            return True
    return False


def _parse_stamp(line: str) -> datetime:
    meta, _, value = line.partition(":")
    value = value.strip()
    tz = None
    if "TZID=" in meta:
        tz = ZoneInfo(meta.split("TZID=", 1)[1].split(";", 1)[0])
    if "T" not in value:
        day = datetime.strptime(value[:8], "%Y%m%d")
        return day.replace(tzinfo=tz or timezone.utc)
    zulu = value.endswith("Z")
    raw = value[:-1] if zulu else value
    stamp = datetime.strptime(raw[:15], "%Y%m%dT%H%M%S")
    if zulu or tz is None:
        return stamp.replace(tzinfo=timezone.utc)
    return stamp.replace(tzinfo=tz)
