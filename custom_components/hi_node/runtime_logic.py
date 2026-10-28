"""Ren fase 2-logikk som kan testes uten Home Assistant."""

from __future__ import annotations

from datetime import datetime


def expire_overrides(
    overrides: dict[str, bool],
    override_until: dict[str, str | None],
    now: datetime,
) -> tuple[dict[str, bool], dict[str, str | None], set[str]]:
    """Nullstill overstyringer når fristen er passert."""
    next_overrides = dict(overrides)
    next_until = dict(override_until)
    changed: set[str] = set()
    for role, raw_deadline in override_until.items():
        if not raw_deadline:
            continue
        try:
            deadline = datetime.fromisoformat(raw_deadline)
        except (TypeError, ValueError):
            deadline = now
        if now >= deadline:
            next_overrides[role] = False
            next_until[role] = None
            changed.add(role)
    return next_overrides, next_until, changed


def next_oven_mismatch(
    mismatch_since: str | None,
    *,
    desired_on: bool,
    oven_on: bool | None,
    power_on: bool | None,
    now: datetime,
    delay_seconds: float,
) -> tuple[str | None, bool]:
    """Beregn kontinuerlig ovnsavvik og alarm etter valgt forsinkelse."""
    mismatching = desired_on and (oven_on is not True or power_on is False)
    if not mismatching:
        return None, False

    since = None
    if mismatch_since:
        try:
            since = datetime.fromisoformat(mismatch_since)
        except (TypeError, ValueError):
            pass
    if since is None:
        since = now
    elapsed = max(0.0, (now - since).total_seconds())
    return since.isoformat(), elapsed >= max(0.0, float(delay_seconds))


def should_notify_alarm(previous: bool, current: bool) -> bool:
    """Varsle bare når alarmen går fra av til på."""
    return bool(current and not previous)
