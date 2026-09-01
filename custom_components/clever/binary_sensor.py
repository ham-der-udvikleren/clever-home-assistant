"""Binary sensor platform for Clever."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CleverDataUpdateCoordinator
from .entity import CleverChargerEntity, find_charger_device_info
from .live_status_coordinator import CleverLiveStatusCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Clever binary sensors."""
    coordinator: CleverDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CleverOnlineSensor(coordinator, charger_id) for charger_id in coordinator.data
    )

    live_status_coordinator: CleverLiveStatusCoordinator | None = hass.data[DOMAIN].get(
        f"{entry.entry_id}_live"
    )
    if live_status_coordinator is not None:
        async_add_entities(
            [
                CleverIsChargingSensor(live_status_coordinator, coordinator),
                CleverStopRequestedSensor(live_status_coordinator, coordinator),
            ]
        )


class CleverOnlineSensor(CleverChargerEntity, BinarySensorEntity):
    """Whether the charger is currently online/reachable."""

    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self, coordinator: CleverDataUpdateCoordinator, charger_unique_id: str
    ) -> None:
        super().__init__(coordinator, charger_unique_id)
        self._attr_unique_id = f"{charger_unique_id}_online"

    @property
    def is_on(self) -> bool:
        return self._charger.is_online


class CleverIsChargingSensor(CoordinatorEntity[CleverLiveStatusCoordinator], BinarySensorEntity):
    """Whether the charger is actively drawing power right now (live add-on only)."""

    _attr_has_entity_name = True
    _attr_translation_key = "is_charging"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    def __init__(
        self, coordinator: CleverLiveStatusCoordinator, main_coordinator: CleverDataUpdateCoordinator
    ) -> None:
        super().__init__(coordinator)
        self._main_coordinator = main_coordinator
        self._attr_unique_id = "clever_live_status_is_charging"

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def device_info(self):
        status = self.coordinator.data
        if status is None:
            return None
        return find_charger_device_info(self._main_coordinator, status.charge_point_id)

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data
        return status.is_charging if status is not None else None


class CleverStopRequestedSensor(CoordinatorEntity[CleverLiveStatusCoordinator], BinarySensorEntity):
    """Whether a stop has been requested for the current charging session."""

    _attr_has_entity_name = True
    _attr_translation_key = "live_stop_requested"

    def __init__(
        self, coordinator: CleverLiveStatusCoordinator, main_coordinator: CleverDataUpdateCoordinator
    ) -> None:
        super().__init__(coordinator)
        self._main_coordinator = main_coordinator
        self._attr_unique_id = "clever_live_status_stop_requested"

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def device_info(self):
        status = self.coordinator.data
        if status is None:
            return None
        return find_charger_device_info(self._main_coordinator, status.charge_point_id)

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.data
        return status.is_stop_requested if status is not None else None
