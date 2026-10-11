"""
Unit tests for calc.py (COP / thermal power). No Home Assistant needed.

Run with:
    python -m pytest tests/test_calc.py -v
"""

import os
import sys
import types

_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _ROOT)

# Same namespace stubs as test_protocol.py, so the package __init__ is not run.
for _name, _path in (
    ("custom_components", os.path.join(_ROOT, "custom_components")),
    ("custom_components.heiko_heatpump", os.path.join(_ROOT, "custom_components", "heiko_heatpump")),
):
    if _name not in sys.modules:
        _pkg = types.ModuleType(_name)
        _pkg.__path__ = [_path]
        sys.modules[_name] = _pkg

from custom_components.heiko_heatpump.calc import heating_efficiency  # noqa: E402

# Live frame from 2026-10-11 19:52, heating at 90 Hz, Ta 7.7 °C. Tw (DHW tank)
# and Tc are 27 K apart and must not influence the result.
HEATING = {
    "WorkingMode": 2.0, "WaterPump": 1.0, "Frequency": 90.0,
    "Tuo": 37.0, "Tui": 32.7, "Tw": 51.4, "Tc": 24.2, "Ta": 7.7,
}


def test_heating_cop_uses_tuo_minus_tui():
    out = heating_efficiency(HEATING, 0.29, 1781.0)
    assert out["Thermal_power"] == round(0.29 * 4186.0 * 4.3, 1)
    assert out["COP_estimated"] == 2.93


def test_carnot_uses_supply_temperature():
    out = heating_efficiency(HEATING, 0.29, 1781.0)
    assert out["COP_carnot"] == round(310.15 / 29.3, 2)


def test_no_cop_outside_heating():
    for change in ({"WorkingMode": 1.0}, {"WaterPump": 0.0}, {"Frequency": 0.0}):
        out = heating_efficiency({**HEATING, **change}, 0.29, 1781.0)
        assert "COP_estimated" not in out and "Thermal_power" not in out
        assert "COP_carnot" in out


def test_no_cop_without_power_or_with_standby_power():
    assert "COP_estimated" not in heating_efficiency(HEATING, 0.29, None)
    assert "COP_estimated" not in heating_efficiency(HEATING, 0.29, 16.0)


def test_implausible_delta_t_rejected():
    for tui in (36.8, 26.0):  # 0.2 K noise, 11 K
        assert "COP_estimated" not in heating_efficiency({**HEATING, "Tui": tui}, 0.29, 1781.0)
