"""Select platform for Clever (smart-charging on/off/timed-disable control)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    SMART_CHARGING_DISABLE_1H,
    SMART_CHARGING_DISABLE_3H,
    SMART_CHARGING_DISABLE_UNTIL_CHARGED,
    SMART_CHARGING_ENABLE,
    SMART_CHARGING_OPTIONS,
)
from .coordinator import CleverDataUpdateCoordinator
from .entity import CleverChargerEntity
from .live_status_coordinator import CleverLiveStatusCoordinator

_TIMEBOX_MINUTES = {
    SMART_CHARGING_DISABLE_1H: 60,
    SMART_CHARGING_DISABLE_3H: 180,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Clever smart-charging select entity."""
    coordinator: CleverDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    live_status_coordinator: CleverLiveStatusCoordinator | None = hass.data[DOMAIN].get(
        f"{entry.entry_id}_live"
    )
    async_add_entities(
        CleverSmartChargingSelect(coordinator, charger_id, live_status_coordinator)
        for charger_id in coordinator.data
    )


class CleverSmartChargingSelect(CleverChargerEntity, SelectEntity, RestoreEntity):
    """Enable/disable smart charging.

    Clever's REST API cannot tell us whether smart charging is currently
    disabled/boosted - the raw strategySettings.disabled field it returns does NOT
    track it (confirmed by testing: it stayed "enabled" through an active boost).
    The live Firestore data does, via `strategy=Boost` plan segments, so when there's
    a current session for this charger it's used as the source of truth. When there's
    no active session to read from, this falls back to being optimistic: it only
    reflects the last command we ourselves sent, restored across HA restarts.
    """

    _attr_translation_key = "smart_charging"
    _attr_options = SMART_CHARGING_OPTIONS

    def __init__(
        self,
        coordinator: CleverDataUpdateCoordinator,
        charger_unique_id: str,
        live_status_coordinator: CleverLiveStatusCoordinator | None,
    ) -> None:
        super().__init__(coordinator, charger_unique_id)
        self._attr_unique_id = f"{charger_unique_id}_smart_charging"
        self._current_option: str | None = None
        self._live_status_coordinator = live_status_coordinator

    @property
    def current_option(self) -> str | None:
        live_status = self._live_status_coordinator.data if self._live_status_coordinator else None
        if live_status is None or live_status.charge_point_id != self._charger.charge_box_id:
            # No current session to read from (no active charge on this charger yet) -
            # the optimistic last-command value is genuinely all we have.
            return self._current_option

        if not live_status.smart_charging_disabled:
            return SMART_CHARGING_ENABLE
        if live_status.schedule_sub_strategy == "Session":
            return SMART_CHARGING_DISABLE_UNTIL_CHARGED
        if live_status.schedule_sub_strategy == "Timebox":
            duration = live_status.boost_duration_minutes
            if duration is not None:
                return min(_TIMEBOX_MINUTES, key=lambda option: abs(_TIMEBOX_MINUTES[option] - duration))
            if self._current_option in _TIMEBOX_MINUTES:
                return self._current_option
            return SMART_CHARGING_DISABLE_1H
        # Disabled, but not by a strategy we recognize - "until charged" is the only
        # indefinite option, so it's the closest honest guess.
        return SMART_CHARGING_DISABLE_UNTIL_CHARGED

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in SMART_CHARGING_OPTIONS:
            self._current_option = last_state.state
        if self._live_status_coordinator is not None:
            self.async_on_remove(
                self._live_status_coordinator.async_add_listener(self.async_write_ha_state)
            )

    async def async_select_option(self, option: str) -> None:
        charger = self._charger
        charge_box_id = charger.charge_box_id
        connector_id = charger.connector_id
        client = self.coordinator.client

        if option == SMART_CHARGING_ENABLE:
            await client.async_unboost(charge_box_id, connector_id)
        elif option == SMART_CHARGING_DISABLE_UNTIL_CHARGED:
            await client.async_boost(charge_box_id, connector_id)
        elif option in _TIMEBOX_MINUTES:
            await client.async_timebox_boost(
                charge_box_id, connector_id, _TIMEBOX_MINUTES[option]
            )
        else:
            return

        self._current_option = option
        self.async_write_ha_state()
