"""Number platform for Clever (desired charge energy)."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    POWER_REQUIRED_MAX_KWH,
    POWER_REQUIRED_MIN_KWH,
    POWER_REQUIRED_STEP_KWH,
)
from .coordinator import CleverDataUpdateCoordinator
from .entity import CleverChargerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Clever power-required number entity."""
    coordinator: CleverDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CleverPowerRequiredNumber(coordinator, charger_id)
        for charger_id, charger in coordinator.data.items()
        if charger.profile is not None
    )


class CleverPowerRequiredNumber(CleverChargerEntity, NumberEntity):
    """Desired charge energy for the next departure (Clever calls this 'power required')."""

    _attr_translation_key = "power_required"
    _attr_native_min_value = POWER_REQUIRED_MIN_KWH
    _attr_native_max_value = POWER_REQUIRED_MAX_KWH
    _attr_native_step = POWER_REQUIRED_STEP_KWH
    _attr_native_unit_of_measurement = "kWh"

    def __init__(
        self, coordinator: CleverDataUpdateCoordinator, charger_unique_id: str
    ) -> None:
        super().__init__(coordinator, charger_unique_id)
        self._attr_unique_id = f"{charger_unique_id}_power_required"

    @property
    def native_value(self) -> float | None:
        profile = self._charger.profile
        return profile.power_required if profile else None

    async def async_set_native_value(self, value: float) -> None:
        profile = self._charger.profile
        if profile is None:
            return
        await self.coordinator.client.async_set_power_required(
            profile.profile_id, int(value)
        )
        await self.coordinator.async_request_refresh()
