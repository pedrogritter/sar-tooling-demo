"""Nearest populated place for a footprint centre.

The list is Natural Earth populated places, reduced to a name and a point.
The catalogue has no place field of its own. A centre farther than 150 km
from every place is open sea, not a city on a distant coast.
"""

from __future__ import annotations

import json
from pathlib import Path

from scene.grid import metres

MAX_DISTANCE_M = 150_000.0
OPEN_SEA = "Open sea"
_PLACES: tuple[tuple[str, float, float], ...] | None = None


def place_name(latitude: float, longitude: float) -> str:
    """Name of the nearest place within 150 km, otherwise open sea."""

    nearest = OPEN_SEA
    best = MAX_DISTANCE_M
    for name, lat, lon in _places():
        distance = metres(latitude, longitude, lat, lon)
        if distance < best:
            best = distance
            nearest = name
    return nearest


def _places() -> tuple[tuple[str, float, float], ...]:
    global _PLACES
    if _PLACES is None:
        path = Path(__file__).with_name("places.json")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise RuntimeError("places.json must be a list")
        loaded: list[tuple[str, float, float]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            lat = item.get("lat")
            lon = item.get("lon")
            if (
                isinstance(name, str)
                and name
                and isinstance(lat, (int, float))
                and isinstance(lon, (int, float))
                and not isinstance(lat, bool)
                and not isinstance(lon, bool)
            ):
                loaded.append((name, float(lat), float(lon)))
        _PLACES = tuple(loaded)
    return _PLACES
