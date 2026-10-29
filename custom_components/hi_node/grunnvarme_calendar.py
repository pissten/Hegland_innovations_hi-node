"""Grunnvarme-kalender: lagring, RRULE-utvidelse og aktiv-vindu."""

from __future__ import annotations

from datetime import date, datetime, timedelta, time
from typing import Any
from uuid import uuid4

from dateutil.rrule import rrulestr

from .features import _clock_minutes

_BYDAY = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
DEFAULT_UID = "grunnvarme-default"
DEFAULT_SUMMARY = "Grunnvarme"


def seed_from_schedule(schedule: dict | None, now: datetime) -> list[dict]:
    """Lag én ukentlig RRULE-oppføring fra config-schedule."""
    event = default_event_from_schedule(schedule, now, uid=DEFAULT_UID)
    return [event] if event else []


def default_event_from_schedule(
    schedule: dict | None, now: datetime, *, uid: str = DEFAULT_UID
) -> dict | None:
    if not isinstance(schedule, dict):
        return None
    try:
        weekdays = sorted({int(day) for day in schedule.get("weekdays", ())})
    except (TypeError, ValueError):
        return None
    start_min = _clock_minutes(schedule.get("start"))
    end_min = _clock_minutes(schedule.get("end"))
    if not weekdays or start_min is None or end_min is None or start_min == end_min:
        return None

    local = now
    if local.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    # Finn nærmeste ukedag i listen (inkl. i dag) for dtstart-anker.
    for offset in range(0, 8):
        day = local.date() + timedelta(days=offset)
        if day.weekday() in weekdays:
            break
    else:
        return None

    dtstart = datetime(
        day.year,
        day.month,
        day.day,
        start_min // 60,
        start_min % 60,
        tzinfo=local.tzinfo,
    )
    if end_min > start_min:
        dtend = datetime(
            day.year,
            day.month,
            day.day,
            end_min // 60,
            end_min % 60,
            tzinfo=local.tzinfo,
        )
    else:
        nxt = day + timedelta(days=1)
        dtend = datetime(
            nxt.year,
            nxt.month,
            nxt.day,
            end_min // 60,
            end_min % 60,
            tzinfo=local.tzinfo,
        )

    byday = ",".join(_BYDAY[day] for day in weekdays)
    return {
        "uid": uid,
        "summary": DEFAULT_SUMMARY,
        "description": "HI-node grunnvarme-timeplan",
        "dtstart": dtstart.isoformat(),
        "dtend": dtend.isoformat(),
        "rrule": f"FREQ=WEEKLY;BYDAY={byday}",
    }


def ensure_seeded(events: list | None, schedule: dict | None, now: datetime) -> list[dict]:
    """Returner eksisterende liste, eller seed fra schedule hvis tom."""
    current = [dict(item) for item in (events or []) if isinstance(item, dict)]
    if current:
        return current
    return seed_from_schedule(schedule, now)


def calendar_active(events: list | None, now: datetime) -> bool:
    """True hvis nå ligger i et utvidet kalendervindu."""
    if not events:
        return False
    window_start = now - timedelta(days=1)
    window_end = now + timedelta(days=1)
    for occurrence in expand_events(events, window_start, window_end):
        start = occurrence["start"]
        end = occurrence["end"]
        if start <= now < end:
            return True
    return False


def expand_events(
    events: list | None, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    """Utvid lagrede (evt. RRULE) oppføringer til konkrete intervaller."""
    found: list[dict[str, Any]] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        try:
            dtstart = _parse_dt(event.get("dtstart"))
            dtend = _parse_dt(event.get("dtend"))
        except (TypeError, ValueError):
            continue
        if dtstart is None or dtend is None or dtend <= dtstart:
            continue
        summary = str(event.get("summary") or DEFAULT_SUMMARY)
        description = event.get("description")
        uid = str(event.get("uid") or "")
        rrule = event.get("rrule")
        duration = dtend - dtstart
        if isinstance(rrule, str) and rrule.strip():
            try:
                rule = rrulestr(rrule, dtstart=dtstart)
                for occurrence in rule.between(start - duration, end, inc=True):
                    occ_start = occurrence
                    if occ_start.tzinfo is None and start.tzinfo is not None:
                        occ_start = occ_start.replace(tzinfo=start.tzinfo)
                    occ_end = occ_start + duration
                    if occ_end <= start or occ_start >= end:
                        continue
                    found.append(
                        {
                            "uid": uid,
                            "summary": summary,
                            "description": description,
                            "start": occ_start,
                            "end": occ_end,
                            "rrule": rrule,
                            "recurrence_id": occ_start.isoformat(),
                        }
                    )
            except (TypeError, ValueError, RecursionError):
                continue
        else:
            if dtend <= start or dtstart >= end:
                continue
            found.append(
                {
                    "uid": uid,
                    "summary": summary,
                    "description": description,
                    "start": dtstart,
                    "end": dtend,
                    "rrule": None,
                    "recurrence_id": None,
                }
            )
    found.sort(key=lambda item: item["start"])
    return found


def create_event_record(**kwargs: Any) -> dict:
    """Ny lagret oppføring fra kalender-UI / service."""
    start = _as_datetime(kwargs["start"])
    end = _as_datetime(kwargs["end"], end=True)
    if end <= start:
        raise ValueError("end must be after start")
    uid = str(kwargs.get("uid") or uuid4())
    record = {
        "uid": uid,
        "summary": str(kwargs.get("summary") or DEFAULT_SUMMARY),
        "description": kwargs.get("description"),
        "dtstart": start.isoformat(),
        "dtend": end.isoformat(),
    }
    rrule = kwargs.get("rrule")
    if isinstance(rrule, str) and rrule.strip():
        record["rrule"] = rrule.strip()
    else:
        record["rrule"] = None
    return record


def update_event_record(events: list[dict], uid: str, **kwargs: Any) -> list[dict]:
    updated: list[dict] = []
    found = False
    for event in events:
        if str(event.get("uid")) != str(uid):
            updated.append(event)
            continue
        found = True
        merged = dict(event)
        if "summary" in kwargs and kwargs["summary"] is not None:
            merged["summary"] = str(kwargs["summary"])
        if "description" in kwargs:
            merged["description"] = kwargs["description"]
        if kwargs.get("start") is not None:
            merged["dtstart"] = _as_datetime(kwargs["start"]).isoformat()
        if kwargs.get("end") is not None:
            merged["dtend"] = _as_datetime(kwargs["end"], end=True).isoformat()
        if "rrule" in kwargs:
            rrule = kwargs["rrule"]
            merged["rrule"] = (
                rrule.strip() if isinstance(rrule, str) and rrule.strip() else None
            )
        updated.append(merged)
    if not found:
        raise KeyError(uid)
    return updated


def delete_event_record(events: list[dict], uid: str) -> list[dict]:
    kept = [event for event in events if str(event.get("uid")) != str(uid)]
    if len(kept) == len(events):
        raise KeyError(uid)
    return kept


def _parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _as_datetime(value, *, end: bool = False) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        # Heldags: slutt-dato er eksklusiv i HA → midnatt den dagen.
        return datetime.combine(value, time.min)
    raise ValueError("start/end must be date or datetime")
