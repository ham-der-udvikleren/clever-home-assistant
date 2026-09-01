"""The Clever integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CleverApiClient
from .const import CONF_LIVE_STATUS_ENABLED, CONF_LIVE_STATUS_URL, CONF_REFRESH_TOKEN, DOMAIN
from .coordinator import CleverDataUpdateCoordinator
from .live_status_coordinator import CleverLiveStatusCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.TIME,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Clever from a config entry."""
    session = async_get_clientsession(hass)
    client = CleverApiClient(session, refresh_token=entry.data[CONF_REFRESH_TOKEN])

    coordinator = CleverDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    live_status_coordinator: CleverLiveStatusCoordinator | None = None
    if entry.data.get(CONF_LIVE_STATUS_ENABLED) and entry.data.get(CONF_LIVE_STATUS_URL):
        live_status_coordinator = CleverLiveStatusCoordinator(
            hass, session, entry.data[CONF_LIVE_STATUS_URL]
        )
        await live_status_coordinator.async_refresh()
    hass.data[DOMAIN][f"{entry.entry_id}_live"] = live_status_coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_live", None)
    return unload_ok
