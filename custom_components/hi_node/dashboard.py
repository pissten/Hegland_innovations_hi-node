"""Melding til ESPHome Device Builder når dashboardet svarer."""

from __future__ import annotations


def compile_message(configuration: str, message_id: str = "1") -> dict:
    """WebSocket-kommandoen firmware/compile."""
    return {
        "command": "firmware/compile",
        "message_id": message_id,
        "args": {"configuration": configuration},
    }


def dashboard_candidates(explicit: str | None = None) -> list[str]:
    """Adresser der dashboardet kan svare fra Home Assistant-noden."""
    found: list[str] = []
    if explicit:
        found.append(explicit.rstrip("/"))
    for base in ("http://127.0.0.1:6052", "http://172.30.32.1:6052"):
        if base not in found:
            found.append(base)
    return found
