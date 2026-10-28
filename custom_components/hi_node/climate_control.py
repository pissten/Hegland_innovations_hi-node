"""Settpunktvalg for climate-modulen."""

from __future__ import annotations


def target_c_for_reason(reason: str, temps: dict) -> float:
    """Velg ønsket temperatur fra booking-hjernens begrunnelse."""
    if reason in ("booking", "manual_override"):
        key = "booking_c"
    elif reason in ("grunnvarme", "frostvakt"):
        key = "grunnvarme_c"
    else:
        key = "default_c"
    return float(temps[key])
