"""number.py ranges must stay inside the limits the controller enforces.

number.py imports Home Assistant, so it is inspected as source with ``ast``.
"""

import ast
import os

_SRC = os.path.join(os.path.dirname(__file__), "..", "custom_components", "heiko_heatpump", "number.py")

# key -> (controller min, controller max). Ranges may be narrower, never wider.
PANEL_LIMITS = {
    "dhw_restart_dt": (2, 15),
    "anti_leg_setpoint": (60, 80),
    "anti_leg_duration": (5, 60),
    "anti_leg_finish": (10, 240),
    "circ_pump_run_time": (1, 10),
    "circ_pump_stop_time": (5, 60),
    "backup_start_delay": (5, 120),
    "f'curve_water_{pt}'": (25, 55),
}


def _descs():
    tree = ast.parse(open(_SRC, encoding="utf-8").read())
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "HeikoNumberEntityDescription":
            kw = {k.arg: k.value for k in node.keywords}
            key = kw["key"].value if isinstance(kw["key"], ast.Constant) else ast.unparse(kw["key"])
            out[key] = (ast.literal_eval(kw["min_value"]), ast.literal_eval(kw["max_value"]))
    return out


def test_every_range_is_valid():
    for key, (lo, hi) in _descs().items():
        assert lo < hi, key


def test_ranges_within_controller_limits():
    descs = _descs()
    for key, (pmin, pmax) in PANEL_LIMITS.items():
        lo, hi = descs[key]
        assert pmin <= lo and hi <= pmax, f"{key}: {lo}..{hi} outside {pmin}..{pmax}"
