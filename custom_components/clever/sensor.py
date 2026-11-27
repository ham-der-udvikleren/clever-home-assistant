"""Sensor platform for Clever."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import CleverDataUpdateCoordinator
from .energy_total import EnergyTotal
from .entity import CleverChargerEntity, CleverLiveStatusEntity
from .live_status_coordinator import CleverLiveStatusCoordinator
from .models import CleverCharger

SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(key="status", translation_key="status"),
    SensorEntityDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(key="model", translation_key="model"),
    SensorEntityDescription(key="phase_count", translation_key="phase_count"),
    SensorEntityDescription(
        key="ampere", translation_key="ampere", native_unit_of_measurement="A"
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Clever sensors."""
    coordinator: CleverDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CleverSensor(coordinator, charger_id, description)
        for charger_id in coordinator.data
        for description in SENSOR_DESCRIPTIONS
    )

    live_status_coordinator: CleverLiveStatusCoordinator | None = hass.data[DOMAIN].get(
        f"{entry.entry_id}_live"
    )
    if live_status_coordinator is not None:
        async_add_entities(
            CleverLiveStatusSensor(live_status_coordinator, coordinator, description)
            for description in LIVE_STATUS_SENSOR_DESCRIPTIONS
        )
        async_add_entities([CleverEnergyTotalSensor(live_status_coordinator, coordinator)])


class CleverSensor(CleverChargerEntity, SensorEntity):
    """A single read-only piece of information about a charger."""

    def __init__(
        self,
        coordinator: CleverDataUpdateCoordinator,
        charger_unique_id: str,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, charger_unique_id)
        self.entity_description = description
        self._attr_unique_id = f"{charger_unique_id}_{description.key}"

    @property
    def native_value(self) -> str | int | datetime | None:
        charger: CleverCharger = self._charger
        key = self.entity_description.key
        if key == "status":
            return charger.detailed_installation_status or charger.installation_status
        if key == "last_seen":
            return dt_util.parse_datetime(charger.last_seen) if charger.last_seen else None
        if key == "model":
            return charger.model_name
        if key == "phase_count":
            return charger.phase_count
        if key == "ampere":
            return charger.ampere
        return None


LIVE_STATUS_SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(key="live_charging_status", translation_key="live_charging_status"),
    SensorEntityDescription(
        key="live_energy_delivered",
        translation_key="live_energy_delivered",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement="kWh",
    ),
    SensorEntityDescription(
        key="live_estimated_finish_time",
        translation_key="live_estimated_finish_time",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="live_session_started_at",
        translation_key="live_session_started_at",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(key="live_status_message", translation_key="live_status_message"),
)


class CleverLiveStatusSensor(CleverLiveStatusEntity, SensorEntity):
    """A read-only piece of live charging-session data (read from Firestore)."""

    def __init__(
        self,
        coordinator: CleverLiveStatusCoordinator,
        main_coordinator: CleverDataUpdateCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, main_coordinator)
        self.entity_description = description
        self._attr_unique_id = f"clever_live_status_{description.key}"

    @property
    def native_value(self) -> str | float | datetime | None:
        status = self.coordinator.data
        if status is None:
            return None
        if self.entity_description.key == "live_charging_status":
            return status.cpms_charging_status
        if self.entity_description.key == "live_energy_delivered":
            return status.total_kwh_delivered
        if self.entity_description.key == "live_estimated_finish_time":
            return status.estimated_finish_time
        if self.entity_description.key == "live_session_started_at":
            return status.session_started_at
        if self.entity_description.key == "live_status_message":
            return status.status_message
        return None

    @property
    def extra_state_attributes(self) -> dict[str, str | None] | None:
        if self.entity_description.key != "live_status_message":
            return None
        status = self.coordinator.data
        if status is None:
            return None
        return {"subtitle": status.status_subtitle, "segment_state": status.segment_state}


@dataclass
class _EnergyTotalStoredData(ExtraStoredData):
    total: EnergyTotal

    def as_dict(self) -> dict[str, Any]:
        return self.total.as_dict()


class CleverEnergyTotalSensor(CleverLiveStatusEntity, RestoreSensor):
    """Total energy delivered by the charger, across all sessions.

    Clever only reports the energy of the current session, so this adds up the
    sessions and keeps the total across restarts. Usable in the energy dashboard.
    """

    _attr_translation_key = "energy_total"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: CleverLiveStatusCoordinator,
        main_coordinator: CleverDataUpdateCoordinator,
    ) -> None:
        super().__init__(coordinator, main_coordinator)
        self._attr_unique_id = "clever_energy_total"
        self._total = EnergyTotal()
        self._restored = False

    @property
    def available(self) -> bool:
        # the total is still valid between sessions, when there is no live data
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> float:
        return round(self._total.total_kwh, 3)

    @property
    def extra_restore_state_data(self) -> _EnergyTotalStoredData:
        return _EnergyTotalStoredData(self._total)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (stored := await self.async_get_last_extra_data()) is not None:
            self._total = EnergyTotal.from_dict(stored.as_dict())
            self._restored = True
        self._update_total()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_total()
        super()._handle_coordinator_update()

    @callback
    def _update_total(self) -> None:
        status = self.coordinator.data
        if status is None:
            return
        session = status.session_id or (
            status.session_started_at.isoformat() if status.session_started_at else None
        )
        if not self._restored:
            # first run: don't count a session that may have ended long ago
            self._total.start_from(session, status.total_kwh_delivered)
            self._restored = True
            return
        self._total.update(session, status.total_kwh_delivered)
