"""DataUpdateCoordinator for the Clever integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CleverApiClient
from .const import CONF_REFRESH_TOKEN, DOMAIN, UPDATE_INTERVAL
from .exceptions import CleverApiError, CleverAuthError
from .models import CleverCharger

_LOGGER = logging.getLogger(__name__)


class CleverDataUpdateCoordinator(DataUpdateCoordinator[dict[str, CleverCharger]]):
    """Polls Clever's backend for installations and charging profiles."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: CleverApiClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.entry = entry
        self.client = client

    async def _async_update_data(self) -> dict[str, CleverCharger]:
        try:
            installations = await self.client.async_get_installations()
            profiles = await self.client.async_get_charging_profiles()
        except CleverAuthError as err:
            raise ConfigEntryAuthFailed("Clever authentication failed") from err
        except CleverApiError as err:
            raise UpdateFailed(f"Error fetching Clever data: {err}") from err

        # Firebase may rotate the refresh token on use; keep the config entry in sync
        # so a HA restart doesn't try to use a stale one.
        if self.client.refresh_token != self.entry.data.get(CONF_REFRESH_TOKEN):
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={**self.entry.data, CONF_REFRESH_TOKEN: self.client.refresh_token},
            )

        profile_by_charge_point = {
            charge_point: profile for profile in profiles for charge_point in profile.charge_points
        }

        chargers: dict[str, CleverCharger] = {}
        for charger in installations:
            charger.profile = profile_by_charge_point.get(
                (charger.charge_box_id, charger.connector_id)
            )
            chargers[charger.unique_id] = charger
        return chargers
