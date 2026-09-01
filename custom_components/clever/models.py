"""Data models for the Clever integration.

These are thin, defensive wrappers around Clever's undocumented mobile-app API
responses (field names/shapes were reverse engineered from captured traffic and
are not guaranteed to be stable).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ChargingProfile:
    """A charging profile (departure time / power required / smart-charging state)."""

    profile_id: str
    charge_points: list[tuple[str, int]]  # (chargeBoxId, connectorId) pairs it applies to
    departure_time: str | None
    power_required: int | None
    happy_hour_enabled: bool

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "ChargingProfile":
        settings = data.get("strategySettings") or {}
        charge_points: list[tuple[str, int]] = []
        for location in (data.get("filters") or {}).get("locations") or []:
            for cp in location.get("chargePoints") or []:
                cp_id = cp.get("id")
                connector_id = cp.get("connectorId")
                if cp_id is not None and connector_id is not None:
                    charge_points.append((str(cp_id), int(connector_id)))
        return cls(
            profile_id=str(data["id"]),
            charge_points=charge_points,
            departure_time=settings.get("departureTime"),
            power_required=settings.get("powerRequired"),
            happy_hour_enabled=bool(settings.get("happyHourEnabled", False)),
        )


@dataclass
class CleverCharger:
    """A single charger installation, merged with its matching charging profile."""

    installation_id: str
    charge_box_id: str
    connector_id: int
    address: str | None
    city: str | None
    postal_code: str | None
    installation_status: str | None
    detailed_installation_status: str | None
    model_name: str | None
    model_series: str | None
    phase_count: int | None
    ampere: int | None
    is_online: bool
    last_seen: str | None

    profile: ChargingProfile | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "CleverCharger":
        charge_box_type = data.get("chargeBoxType") or {}
        smart_config = (
            (data.get("smartChargingConfiguration") or {}).get("userConfiguration") or {}
        )
        configured_effect = smart_config.get("configuredEffect") or {}
        return cls(
            installation_id=str(data["installationId"]),
            charge_box_id=str(data["chargeBoxId"]),
            connector_id=int(data.get("connectorId", 1)),
            address=data.get("address"),
            city=data.get("city"),
            postal_code=data.get("postalCode"),
            installation_status=data.get("installationStatus"),
            detailed_installation_status=data.get("detailedInstallationStatus"),
            model_name=charge_box_type.get("name"),
            model_series=data.get("modelSeries"),
            phase_count=configured_effect.get("phaseCount"),
            ampere=configured_effect.get("ampere"),
            is_online=bool(data.get("isOnline", False)),
            last_seen=data.get("lastSeen"),
        )

    @property
    def unique_id(self) -> str:
        """Stable unique id for this charger, used as the HA device identifier."""
        return f"{self.charge_box_id}_{self.connector_id}"

    @property
    def name(self) -> str:
        return self.model_name or f"Clever charger {self.charge_box_id}"
