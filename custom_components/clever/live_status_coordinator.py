"""DataUpdateCoordinator for the live charging status (read directly from Firestore)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CleverApiClient
from .const import DOMAIN, LIVE_STATUS_UPDATE_INTERVAL
from .exceptions import CleverApiError, CleverAuthError
from .live_status import LiveChargingStatus, parse_transactions_response

_LOGGER = logging.getLogger(__name__)


class CleverLiveStatusCoordinator(DataUpdateCoordinator[LiveChargingStatus | None]):
    """Polls the account's live charging session from Firestore."""

    def __init__(self, hass: HomeAssistant, client: CleverApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_live_status",
            update_interval=LIVE_STATUS_UPDATE_INTERVAL,
        )
        self._client = client

    async def _async_update_data(self) -> LiveChargingStatus | None:
        try:
            payload = await self._client.async_get_active_transactions()
        except CleverAuthError as err:
            # Auth failures are handled/reported by the main coordinator's reauth flow;
            # here just surface it as a soft failure so live entities go unavailable.
            raise UpdateFailed(f"Clever authentication failed: {err}") from err
        except CleverApiError as err:
            raise UpdateFailed(f"Error fetching Clever live status: {err}") from err

        return parse_transactions_response(
            payload, captured_at_fallback=datetime.now(timezone.utc)
        )
