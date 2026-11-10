"""Consistency checks for the setdata slot map and the sensors built on it.

coordinator.py / sensor.py import Home Assistant, which is not needed here, so
both files are read as source and inspected with ``ast``.
"""

import ast
import os

_PKG = os.path.join(os.path.dirname(__file__), "..", "custom_components", "heiko_heatpump")

# Read-only diagnostic slots added in 1.15.0 (idx -> key).
NEW_SLOTS = {
    5: "Mode_DHW_Enabled", 6: "Mode_Heating_Enabled", 7: "Mode_Cooling_Enabled",
    12: "Low_Freq_Run_Duration",
    13: "Heating_Setpoint_Max", 14: "Heating_Setpoint_Min",
    15: "Cooling_Setpoint_Max", 16: "Cooling_Setpoint_Min",
    75: "Circuit2_Setpoint_Max", 76: "Circuit2_Setpoint_Min",
    107: "Frost_L1_Ambient_Start", 108: "Frost_L2_Ambient_Start",
    109: "Frost_L2_Ambient_Stop", 110: "Frost_L2_Water_Start",
    111: "Frost_L2_Water_Stop",
}
FORBIDDEN_IDX = {112, 113, *range(114, 120), *range(122, 130)}


def _setdata_map():
    tree = ast.parse(open(os.path.join(_PKG, "coordinator.py"), encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "_SETDATA_MAP":
            return [ast.literal_eval(e) for e in node.value.elts]
    raise AssertionError("_SETDATA_MAP not found")


def _sensor_keys():
    tree = ast.parse(open(os.path.join(_PKG, "sensor.py"), encoding="utf-8").read())
    keys = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "HeikoSensorEntityDescription":
            for kw in node.keywords:
                if kw.arg == "key":
                    keys.append(ast.literal_eval(kw.value))
    return keys


def test_idx_and_keys_unique():
    entries = _setdata_map()
    idxs = [e[0] for e in entries]
    keys = [e[1] for e in entries]
    assert len(idxs) == len(set(idxs))
    assert len(keys) == len(set(keys))


def test_new_slots_present():
    by_idx = {e[0]: e[1] for e in _setdata_map()}
    for idx, key in NEW_SLOTS.items():
        assert by_idx.get(idx) == key


def test_dealer_and_unconfirmed_slots_not_mapped():
    assert not FORBIDDEN_IDX & {e[0] for e in _setdata_map()}


def test_new_slots_have_sensors():
    keys = _sensor_keys()
    for key in NEW_SLOTS.values():
        assert keys.count(key) == 1
