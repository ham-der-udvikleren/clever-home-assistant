"""Total energy sensor (issue #5)."""
import pytest

from .conftest import entity_id, transactions


async def test_total_energy_adds_up_sessions(hass, api, setup_integration, refresh_live):
    api["state"]["live"] = transactions(session="old", wh=9000)
    entry = await setup_integration()
    total = entity_id(hass, "sensor", "clever_energy_total")
    state = hass.states.get(total)
    # a session that was already there at install time is not counted
    assert float(state.state) == 0
    assert state.attributes["state_class"] == "total_increasing"
    assert state.attributes["unit_of_measurement"] == "kWh"

    for session, wh in (("s1", 1500), ("s1", 4000), ("s2", 500), ("s2", 2250)):
        api["state"]["live"] = transactions(session=session, wh=wh)
        await refresh_live(entry)
    assert float(hass.states.get(total).state) == pytest.approx(6.25)

    # between sessions there is no live data, but the total stays available
    api["state"]["live"] = {}
    await refresh_live(entry)
    assert float(hass.states.get(total).state) == pytest.approx(6.25)
