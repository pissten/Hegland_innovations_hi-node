"""Helsebom mot HI Booking. Tre bom, minst ett minutt mellom."""

from __future__ import annotations

from datetime import datetime, timedelta


class HealthTracker:
    """Teller sammenhengende bom og bytter til iCal etter den tredje."""

    def __init__(self) -> None:
        self.failures = 0
        self.fallback = False
        self._last: datetime | None = None

    def record(self, ok: bool, now: datetime) -> bool:
        """Registrer ett forsøk. Returnerer True når reserven nettopp ble slått av."""
        if ok:
            cleared = self.fallback
            self.failures = 0
            self.fallback = False
            self._last = None
            return cleared
        if self._last is None or now - self._last >= timedelta(minutes=1):
            self.failures += 1
            self._last = now
        if self.failures >= 3:
            self.fallback = True
        return False
