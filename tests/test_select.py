"""Smart charging select (issue #2)."""
import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.clever.exceptions import CleverApiError

from .conftest import CHARGE_BOX, entity_id, transactions

SELECT = f"{CHARGE_BOX}_1_smart_charging"


async def test_shows_command_until_plan_changes(hass, api, setup_integration, refresh_live):
    entry = await setup_integration()
    select = entity_id(hass, "select", SELECT)
    assert hass.states.get(select).state == "enable"

    await hass.services.async_call(
        "select", "select_option", {"entity_id": select, "option": "disable_1h"}, blocking=True
    )
    api["timebox"].assert_awaited_once_with(CHARGE_BOX, 1, 60)
    # Clever has not updated its plan yet: the command is shown, not the old plan
    assert hass.states.get(select).state == "disable_1h"
    await refresh_live(entry)
    assert hass.states.get(select).state == "disable_1h"

    # Clever's plan changes: from now on the live plan is the truth
    api["state"]["live"] = transactions(revision=2, strategy="Smart")
    await refresh_live(entry)
    assert hass.states.get(select).state == "enable"


async def test_failed_command_is_reported(hass, api, setup_integration):
    await setup_integration()
    api["unboost"].side_effect = CleverApiError("Clever API returned 504")
    with pytest.raises(HomeAssistantError, match="504"):
        await hass.services.async_call(
            "select", "select_option",
            {"entity_id": entity_id(hass, "select", SELECT), "option": "enable"}, blocking=True,
        )
