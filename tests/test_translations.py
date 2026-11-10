"""Every translation file must have exactly the same keys and placeholders as en.json."""

import json
import os
import re

_DIR = os.path.join(os.path.dirname(__file__), "..", "custom_components", "heiko_heatpump", "translations")


def _flat(d, prefix=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flat(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def _load(name):
    with open(os.path.join(_DIR, name), encoding="utf-8") as f:
        return _flat(json.load(f))


def test_translations_match_en():
    en = _load("en.json")
    for name in os.listdir(_DIR):
        if name == "en.json" or not name.endswith(".json"):
            continue
        tr = _load(name)
        assert tr.keys() == en.keys(), name
        for k in en:
            assert set(re.findall(r"\{\w+\}", en[k])) == set(re.findall(r"\{\w+\}", tr[k])), f"{name}:{k}"
