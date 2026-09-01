"""Common base entity for Clever platforms."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CleverDataUpdateCoordinator
from .models import CleverCharger


class CleverChargerEntity(CoordinatorEntity[CleverDataUpdateCoordinator]):
    """Base entity tied to one charger installation."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: CleverDataUpdateCoordinator, charger_unique_id: str
    ) -> None:
        super().__init__(coordinator)
        self._charger_unique_id = charger_unique_id

    @property
    def _charger(self) -> CleverCharger:
        return self.coordinator.data[self._charger_unique_id]

    @property
    def available(self) -> bool:
        return super().available and self._charger_unique_id in self.coordinator.data

    @property
    def device_info(self) -> DeviceInfo:
        charger = self._charger
        return DeviceInfo(
            identifiers={(DOMAIN, charger.unique_id)},
            name=charger.name,
            manufacturer="Clever",
            model=charger.model_series or charger.model_name,
            serial_number=charger.charge_box_id,
        )


def find_charger_device_info(
    coordinator: CleverDataUpdateCoordinator, charge_point_id: str
) -> DeviceInfo | None:
    """Find the device_info for whichever charger matches a live-status charge_point_id."""
    for charger in coordinator.data.values():
        if charger.charge_box_id == charge_point_id:
            return DeviceInfo(
                identifiers={(DOMAIN, charger.unique_id)},
                name=charger.name,
                manufacturer="Clever",
                model=charger.model_series or charger.model_name,
                serial_number=charger.charge_box_id,
            )
    return None
