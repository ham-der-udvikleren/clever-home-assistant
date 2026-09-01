"""Time platform for Clever (departure time)."""
from __future__ import annotations

from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEPARTURE_TIME_STEP_MINUTES, DOMAIN
from .coordinator import CleverDataUpdateCoordinator
from .entity import CleverChargerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Clever departure-time entity."""
    coordinator: CleverDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CleverDepartureTime(coordinator, charger_id)
        for charger_id, charger in coordinator.data.items()
        if charger.profile is not None
    )


def _round_to_step(value: dt_time, step_minutes: int) -> dt_time:
    """Round a time value to the nearest step-minute boundary."""
    total_minutes = value.hour * 60 + value.minute
    rounded = round(total_minutes / step_minutes) * step_minutes
    rounded %= 24 * 60
    return dt_time(hour=rounded // 60, minute=rounded % 60)


class CleverDepartureTime(CleverChargerEntity, TimeEntity):
    """The time the car should be ready to leave by.

    Clever only accepts departure times on 5-minute boundaries; values are
    rounded to the nearest one before being sent.
    """

    _attr_translation_key = "departure_time"

    def __init__(
        self, coordinator: CleverDataUpdateCoordinator, charger_unique_id: str
    ) -> None:
        super().__init__(coordinator, charger_unique_id)
        self._attr_unique_id = f"{charger_unique_id}_departure_time"

    @property
    def native_value(self) -> dt_time | None:
        profile = self._charger.profile
        if profile is None or not profile.departure_time:
            return None
        hour, minute = profile.departure_time.split(":")
        return dt_time(hour=int(hour), minute=int(minute))

    async def async_set_value(self, value: dt_time) -> None:
        profile = self._charger.profile
        if profile is None:
            return
        rounded = _round_to_step(value, DEPARTURE_TIME_STEP_MINUTES)
        await self.coordinator.client.async_set_departure_time(
            profile.profile_id, f"{rounded.hour:02d}:{rounded.minute:02d}"
        )
        await self.coordinator.async_request_refresh()
