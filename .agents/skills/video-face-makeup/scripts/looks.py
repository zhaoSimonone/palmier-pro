"""Named makeup looks. 轻薄暖桃妆 is the default calibrated look."""
from __future__ import annotations

from typing import Any

LOOKS: dict[str, dict[str, Any]] = {
    "warm-peach": {
        "id": "warm-peach",
        "display_name": "轻薄暖桃妆",
        "aliases": ("peach", "暖桃妆", "轻薄暖桃妆", "warm peach"),
        "description": "Thin warm peach makeup: apple blush, coral lip, faint lid, slight face warmth.",
        "layers": ("warmth", "blush", "lips", "lids", "smooth"),
        "warm": 0.55,
        "warm_bgr": (1.0, 3.2, 8.0),
        "blush": 0.62,
        "blush_bgr": (5.0, 12.0, 44.0),
        "lips": 0.48,
        "lips_bgr": (4.0, 6.0, 30.0),
        "lids": 0.30,
        "lids_bgr": (0.0, 5.0, 16.0),
        "smooth": 0.18,
        "cheek_sx": 0.42,
        "cheek_sy": 0.30,
        "nose_blush": 0.32,
    }
}

_ALIAS = {}
for _look in LOOKS.values():
    _ALIAS[_look["id"]] = _look["id"]
    for _alias in _look["aliases"]:
        _ALIAS[_alias.lower()] = _look["id"]


def resolve_look(name: str) -> dict[str, Any]:
    key = name.strip().lower()
    look_id = _ALIAS.get(key)
    if look_id is None:
        known = ", ".join(sorted(LOOKS))
        raise ValueError(f"unknown look {name!r}; known: {known}")
    return LOOKS[look_id]


def list_looks() -> list[dict[str, Any]]:
    return [LOOKS[key] for key in sorted(LOOKS)]
