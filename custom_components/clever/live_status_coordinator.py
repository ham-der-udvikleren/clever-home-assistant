"""DataUpdateCoordinator for the optional live-status add-on."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LIVE_STATUS_UPDATE_INTERVAL
from .live_status import LiveChargingStatus, parse_status_response

_LOGGER = logging.getLogger(__name__)


class CleverLiveStatusCoordinator(DataUpdateCoordinator[LiveChargingStatus | None]):
    """Polls the live-status add-on's /status endpoint, if configured."""

    def __init__(self, hass: HomeAssistant, session: aiohttp.ClientSession, url: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_live_status",
            update_interval=LIVE_STATUS_UPDATE_INTERVAL,
        )
        self._session = session
        self._url = url

    async def _async_update_data(self) -> LiveChargingStatus | None:
        try:
            async with self._session.get(self._url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                payload = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Error fetching live status from {self._url}: {err}") from err

        return parse_status_response(payload, captured_at_fallback=datetime.now(timezone.utc))
