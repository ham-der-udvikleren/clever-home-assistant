"""Shared fixtures: a Home Assistant with the Clever integration and a fake Clever API."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.clever.const import DOMAIN
from custom_components.clever.models import CleverCharger

pytest_plugins = "pytest_homeassistant_custom_component"

CHARGE_BOX = "CB1"
INSTALLATION = {
    "installationId": "1", "chargeBoxId": CHARGE_BOX, "connectorId": 1,
    "chargeBoxType": {"name": "P40"}, "isOnline": True,
}


def transactions(session="s1", wh=0, revision=1, strategy="Smart"):
    """Firestore REST response with one active transaction."""
    return {"documents": [{"fields": {
        "sessionId": {"stringValue": session},
        "chargePointId": {"stringValue": CHARGE_BOX},
        "chargingStart": {"timestampValue": "2026-11-27T18:00:00Z"},
        "consumedWh": {"integerValue": str(wh)},
        "cpmsChargingStatus": {"stringValue": "Charging"},
        "chargingPlan": {"mapValue": {"fields": {
            "revisionNumber": {"integerValue": str(revision)},
            "segments": {"arrayValue": {"values": [{"mapValue": {"fields": {
                "start": {"timestampValue": "2026-11-27T18:00:00Z"},
                "end": {"timestampValue": "2026-11-27T19:00:00Z"},
                "reason": {"mapValue": {"fields": {"strategy": {"stringValue": strategy}}}},
            }}}]}},
        }}},
    }}]}


@pytest.fixture
def api(enable_custom_integrations):
    """Patch the Clever API client. Set api["state"]["live"] to change the live data."""
    state = {"live": transactions()}
    client = "custom_components.clever.api.CleverApiClient"
    with (
        patch(f"{client}.async_get_installations",
              AsyncMock(side_effect=lambda: [CleverCharger.from_api(INSTALLATION)])),
        patch(f"{client}.async_get_charging_profiles", AsyncMock(return_value=[])),
        patch(f"{client}.async_get_active_transactions",
              AsyncMock(side_effect=lambda: state["live"])),
        patch(f"{client}.async_timebox_boost", AsyncMock()) as timebox,
        patch(f"{client}.async_unboost", AsyncMock()) as unboost,
        patch(f"{client}.async_ensure_token", AsyncMock()),
    ):
        yield {"state": state, "timebox": timebox, "unboost": unboost}


@pytest.fixture
def setup_integration(hass, api):
    """Set up the integration; returns the config entry."""
    async def _setup():
        entry = MockConfigEntry(domain=DOMAIN, data={"email": "a@b.dk", "refresh_token": "t"})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry
    return _setup


@pytest.fixture
def refresh_live(hass):
    """Poll the live status now instead of waiting 10 seconds."""
    async def _refresh(entry):
        await hass.data[DOMAIN][f"{entry.entry_id}_live"].async_refresh()
        await hass.async_block_till_done()
    return _refresh


def entity_id(hass, platform, unique_id):
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
