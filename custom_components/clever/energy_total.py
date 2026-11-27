"""Running total of the energy delivered by the charger, across sessions.

Clever only exposes the energy delivered in the current session, which starts
from zero on every new session. This keeps a total that only ever grows, so the
charger can be used in the Home Assistant energy dashboard. Kept free of Home
Assistant imports so it can be tested on its own.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class EnergyTotal:
    """Total kWh delivered, plus the session it was last updated from."""

    total_kwh: float = 0.0
    session: str | None = None
    session_kwh: float = 0.0

    def update(self, session: str | None, session_kwh: float | None) -> bool:
        """Add what the session has delivered since the last update.

        Returns True if the total changed.
        """
        if session is None or session_kwh is None or session_kwh < 0:
            return False
        if session != self.session:
            # a new session: everything delivered in it so far is new energy
            self.session, self.session_kwh = session, session_kwh
            self.total_kwh += session_kwh
            return session_kwh > 0
        if session_kwh <= self.session_kwh:
            # same session, nothing new (a lower value is a glitch, not a reset)
            return False
        self.total_kwh += session_kwh - self.session_kwh
        self.session_kwh = session_kwh
        return True

    def start_from(self, session: str | None, session_kwh: float | None) -> None:
        """Remember the current session without counting it.

        Used the first time the sensor runs, so a session that ended before the
        integration was installed is not counted as new energy.
        """
        if session is not None and session_kwh is not None:
            self.session, self.session_kwh = session, session_kwh

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnergyTotal:
        return cls(
            total_kwh=float(data.get("total_kwh") or 0.0),
            session=data.get("session"),
            session_kwh=float(data.get("session_kwh") or 0.0),
        )
