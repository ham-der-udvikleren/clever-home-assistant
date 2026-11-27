"""Live entities are linked to the charger device without the deprecated lookup."""
from unittest.mock import patch

from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import CHARGE_BOX, entity_id


async def test_live_entities_link_to_charger_device(hass, api, setup_integration, refresh_live):
    with patch.object(
        dr.DeviceRegistry, "async_get_device", wraps=dr.async_get(hass).async_get_device
    ) as deprecated:
        entry = await setup_integration()
        await refresh_live(entry)
    deprecated.assert_not_called()

    registry = er.async_get(hass)
    live = registry.async_get(entity_id(hass, "sensor", "clever_live_status_live_energy_delivered"))
    select = registry.async_get(entity_id(hass, "select", f"{CHARGE_BOX}_1_smart_charging"))
    assert live.device_id is not None
    assert live.device_id == select.device_id
