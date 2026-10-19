"""Common base entity for Clever platforms."""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CleverDataUpdateCoordinator
from .live_status_coordinator import CleverLiveStatusCoordinator
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


class CleverLiveStatusEntity(CoordinatorEntity[CleverLiveStatusCoordinator]):
    """Base entity for data from the optional live-status add-on.

    Not tied to a fixed charger - it belongs to whichever charger the live session is
    on, so its device is only known once the add-on has actually returned data.
    """

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: CleverLiveStatusCoordinator, main_coordinator: CleverDataUpdateCoordinator
    ) -> None:
        super().__init__(coordinator)
        self._main_coordinator = main_coordinator

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def device_info(self) -> DeviceInfo | None:
        status = self.coordinator.data
        if status is None:
            return None
        return find_charger_device_info(self._main_coordinator, status.charge_point_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._async_link_to_charger_device()
        super()._handle_coordinator_update()

    @callback
    def _async_link_to_charger_device(self) -> None:
        """Link this entity to its charger's device, once live data says which one that is.

        HA only reads device_info when an entity is added - so if HA started (or the
        integration reloaded) while the add-on was unreachable, the entity got registered
        with no device (detaching it from its charger), and nothing would re-attach it
        short of another manual reload, even after the add-on came back.
        """
        device_info = self.device_info
        if device_info is None or self.registry_entry is None:
            return
        device = dr.async_get(self.hass).async_get_device(identifiers=device_info["identifiers"])
        if device is not None and device.id != self.registry_entry.device_id:
            er.async_get(self.hass).async_update_entity(self.entity_id, device_id=device.id)
