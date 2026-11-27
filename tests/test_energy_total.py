"""Tests for the running energy total (no Home Assistant needed)."""
import importlib.util
import sys
from pathlib import Path

_PATH = Path(__file__).parents[1] / "custom_components" / "clever" / "energy_total.py"
_spec = importlib.util.spec_from_file_location("energy_total", _PATH)
energy_total = importlib.util.module_from_spec(_spec)
sys.modules["energy_total"] = energy_total  # needed by @dataclass
_spec.loader.exec_module(energy_total)
EnergyTotal = energy_total.EnergyTotal


def test_adds_growth_within_a_session():
    t = EnergyTotal()
    t.update("a", 1.0)
    assert t.update("a", 2.5)
    assert t.total_kwh == 2.5


def test_new_session_starts_from_zero():
    t = EnergyTotal()
    t.update("a", 10.0)
    t.update("b", 0.4)
    t.update("b", 3.0)
    assert t.total_kwh == 13.0


def test_ignores_drops_and_missing_values():
    t = EnergyTotal()
    t.update("a", 5.0)
    assert not t.update("a", 4.0)
    assert not t.update("a", None)
    assert not t.update(None, 7.0)
    assert t.update("a", 6.0)
    assert t.total_kwh == 6.0


def test_same_value_again_is_not_counted_twice():
    t = EnergyTotal()
    t.update("a", 5.0)
    assert not t.update("a", 5.0)
    assert t.total_kwh == 5.0


def test_start_from_does_not_count_an_old_session():
    t = EnergyTotal()
    t.start_from("old", 12.0)
    t.update("old", 12.0)
    assert t.total_kwh == 0.0
    t.update("old", 12.5)  # the old session was still running
    t.update("new", 2.0)
    assert t.total_kwh == 2.5


def test_round_trip():
    t = EnergyTotal(total_kwh=42.1, session="x", session_kwh=3.2)
    assert EnergyTotal.from_dict(t.as_dict()) == t
    assert EnergyTotal.from_dict({}) == EnergyTotal()
