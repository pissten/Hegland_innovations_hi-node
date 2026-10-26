"""Synk av før/etter mot booking. Siste endring gjelder, unntatt første gang."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .const import DEFAULT_MARGINS, ROLES

_LIMITS = {"oven": 180, "door": 60, "light": 60}


def clamp_margin(role: str, value) -> int | None:
    limit = _LIMITS.get(role)
    if limit is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(limit, number))


def margin_payload(margins: dict) -> dict:
    payload = {}
    for role in ROLES:
        pair = margins.get(role) or DEFAULT_MARGINS[role]
        pre = clamp_margin(role, pair[0])
        post = clamp_margin(role, pair[1])
        if pre is None or post is None:
            continue
        payload[role] = [pre, post]
    return payload


def margins_url(ical_url: str | None) -> str | None:
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
    return urlunsplit((parts.scheme, parts.netloc, "/node/margins", kept, ""))


def parse_margin_document(payload: dict) -> tuple[str | None, dict]:
    if not isinstance(payload, dict):
        return None, {}
    raw_stamp = payload.get("updatedAt") or payload.get("updated_at")
    stamp = str(raw_stamp) if raw_stamp else None
    raw = payload.get("margins") if isinstance(payload.get("margins"), dict) else {}
    margins = {}
    for role in ROLES:
        pair = raw.get(role)
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        pre = clamp_margin(role, pair[0])
        post = clamp_margin(role, pair[1])
        if pre is None or post is None:
            continue
        margins[role] = [pre, post]
    return stamp, margins


def apply_remote_margins(local: dict, remote: dict) -> bool:
    changed = False
    for role, pair in remote.items():
        if role not in ROLES:
            continue
        current = list(local.get(role) or DEFAULT_MARGINS[role])
        if current[0] != pair[0] or current[1] != pair[1]:
            local[role] = [pair[0], pair[1]]
            changed = True
    return changed


def margin_sync_action(*, seeded: bool, dirty: bool, seen_at: str | None, remote_at: str | None) -> str:
    """push første gang og ved lokal endring. pull når booking er nyere."""
    if not seeded or dirty:
        return "push"
    if remote_at and remote_at != (seen_at or ""):
        return "pull"
    return "idle"
