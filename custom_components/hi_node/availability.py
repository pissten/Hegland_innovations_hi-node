"""Nød-stenging mot booking. Samme slug og token som kalenderen."""

from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Valg i HA: timer, eller resten av dagen.
DURATION_OPTIONS = (
    ("60", "1 time"),
    ("120", "2 timer"),
    ("240", "4 timer"),
    ("rest", "Resten av dagen"),
)
DEFAULT_DURATION_KEY = "120"


def availability_url(ical_url: str | None) -> str | None:
    """Samme vert, slug og token som kalenderen."""
    if not ical_url:
        return None
    parts = urlsplit(str(ical_url).strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    slug = str(query.get("slug") or "").strip()
    if not slug:
        return None
    kept = urlencode({"slug": slug, "token": query.get("token", "")})
    return urlunsplit((parts.scheme, parts.netloc, "/node/availability", kept, ""))


def duration_minutes_for(key: str, now: datetime) -> int:
    """Minutter til PUT, eller til midnatt for resten av dagen."""
    raw = str(key or DEFAULT_DURATION_KEY).strip().lower()
    if raw == "rest":
        local = now
        midnight = local.replace(hour=23, minute=59, second=0, microsecond=0)
        if midnight <= local:
            midnight = midnight + timedelta(days=1)
        return max(1, int(round((midnight - local).total_seconds() / 60)))
    try:
        minutes = int(raw)
    except ValueError:
        minutes = int(DEFAULT_DURATION_KEY)
    return max(1, minutes)


def parse_availability_document(payload: dict | None) -> dict:
    """Normaliser GET/PUT-svar fra booking."""
    if not isinstance(payload, dict):
        return {"active": False, "ends_at": None, "starts_at": None, "block_id": None, "duration_minutes": None}
    active = bool(payload.get("active"))
    ends = payload.get("endsAt") or payload.get("ends_at")
    starts = payload.get("startsAt") or payload.get("starts_at")
    duration = payload.get("durationMinutes")
    if duration is None:
        duration = payload.get("duration_minutes")
    try:
        duration_min = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_min = None
    return {
        "active": active,
        "ends_at": str(ends) if ends else None,
        "starts_at": str(starts) if starts else None,
        "block_id": payload.get("blockId") or payload.get("block_id"),
        "duration_minutes": duration_min,
    }


def format_closed_until(ends_at: str | None, now: datetime) -> str:
    """Kort tekst til sensoren."""
    if not ends_at:
        return "Åpen"
    try:
        end = datetime.fromisoformat(str(ends_at).replace("Z", "+00:00"))
    except ValueError:
        return "Åpen"
    if now.tzinfo and end.tzinfo is None:
        end = end.replace(tzinfo=now.tzinfo)
    elif now.tzinfo and end.tzinfo:
        end = end.astimezone(now.tzinfo)
    if end <= now:
        return "Åpen"
    return f"Stengt til {end:%H:%M}"
