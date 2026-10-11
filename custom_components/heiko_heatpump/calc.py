"""Derived heating-efficiency values (pure Python, no Home Assistant imports)."""

from __future__ import annotations

WATER_HEAT_CAPACITY = 4186.0  # J/(kg·K); 1 L of water ≈ 1 kg


def heating_efficiency(
    params: dict[str, float], flow_rate_lps: float, input_power_w: float | None
) -> dict[str, float]:
    """
    Return COP_carnot, Thermal_power and COP_estimated for one realtime frame.

    The water-side ΔT is Tuo − Tui: supply and return of the unit's own plate
    heat exchanger, i.e. the water the configured flow rate actually passes
    through. (Before 1.14.0 this used Tw − Tc, but Tw is the DHW tank and Tc
    the heating-circuit water — two different circuits, so the "ΔT" was
    17–34 K in normal heating and the COP never appeared or was nonsense.)

    input_power_w is whatever the caller trusts most: an external meter if one
    is configured, otherwise the pump's own V × I.
    """
    out: dict[str, float] = {}
    tuo = params.get("Tuo")
    tui = params.get("Tui")
    ta = params.get("Ta")

    if tuo is not None and ta is not None and tuo - ta > 0.1:
        out["COP_carnot"] = round((tuo + 273.15) / (tuo - ta), 2)

    # Heating only (WorkingMode 2) with the compressor actually running.
    frequency = params.get("Frequency")
    if (params.get("WorkingMode") != 2.0 or params.get("WaterPump") != 1.0
            or tuo is None or tui is None or input_power_w is None
            or frequency is None or frequency <= 5.0 or input_power_w <= 50.0):
        return out
    dt = tuo - tui
    # Below 0.5 K sensor noise dominates; above 10 K the flow is clearly not
    # the nominal one the calculation assumes.
    if 0.5 < dt <= 10.0:
        q_thermal = flow_rate_lps * WATER_HEAT_CAPACITY * dt
        out["Thermal_power"] = round(q_thermal, 1)
        out["COP_estimated"] = round(q_thermal / input_power_w, 2)
    return out
