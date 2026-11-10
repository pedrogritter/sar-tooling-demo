"""Load a coarse GRD or dwell overview and convert it to sigma-nought.

The full raster stays on disk. Measurements use the COG overview nearest
a few thousand pixels on a side, the same budget as the Lisbon reader.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import cast

import numpy as np
import tifffile

from scene.grid import Grid, metres

# Used only when this collect is the Lisbon test scene and its sidecar
# does not repeat the factor already measured for that GRD.
LISBON_SCENE_ID = "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF"
LISBON_CALIBRATION = 1.3405353724476985e-05
_CALIBRATION_KEYS = (
    "iceye:calibration_factor",
    "sar:calibration_factor",
    "calibration_factor",
)
OVERVIEW_SIDE = 1600


def load_amplitude(path: Path, side: int = OVERVIEW_SIDE) -> tuple[np.ndarray, float]:
    """Return a 2-D overview and the full-pixel scale of one overview pixel."""

    with tifffile.TiffFile(path) as tiff:
        series = tiff.series[0]
        full = series.levels[0]
        chosen = full
        for level in series.levels:
            longest = max(int(level.shape[0]), int(level.shape[1]))
            if longest <= side:
                chosen = level
                break
        array = np.asarray(chosen.asarray())
        full_shape = (int(full.shape[0]), int(full.shape[1]))
    if array.ndim == 3 and array.shape[-1] in {3, 4}:
        array = np.moveaxis(array, -1, 0).mean(axis=0)
    elif array.ndim == 3 and array.shape[0] in {3, 4}:
        array = array.mean(axis=0)
    elif array.ndim != 2:
        raise RuntimeError(f"{path.name} is not a single-band overview")
    scale = full_shape[0] / array.shape[0]
    other = full_shape[1] / array.shape[1]
    if abs(scale - other) > 0.05:
        raise RuntimeError(f"{path.name} overview axes do not share a scale")
    return np.asarray(array, dtype=np.float32), float(scale)


def load_video(path: Path, side: int = 1200) -> tuple[np.ndarray, float]:
    """Return a frames-first dwell overview and its full-pixel scale."""

    with tifffile.TiffFile(path) as tiff:
        series = tiff.series[0]
        full = series.levels[0]
        chosen = full
        for level in series.levels:
            longest = max(int(level.shape[0]), int(level.shape[1]))
            if longest <= side:
                chosen = level
                break
        array = np.asarray(chosen.asarray())
        full_h = int(full.shape[0])
        full_w = int(full.shape[1])
    if array.ndim != 3:
        raise RuntimeError(f"{path.name} is not a dwell stack")
    if array.shape[-1] <= 64:
        array = np.moveaxis(array, -1, 0)
    scale = full_h / array.shape[1]
    other = full_w / array.shape[2]
    if abs(scale - other) > 0.05:
        raise RuntimeError(f"{path.name} overview axes do not share a scale")
    return np.asarray(array, dtype=np.float32), float(scale)


def read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path.name} is not a JSON object")
    return payload


def calibration_factor(grd_meta: dict[str, object], scene_id: str) -> float | None:
    """Linear factor such that sigma0 = factor * DN^2. None when uncalibrated."""

    found = _find_factor(grd_meta)
    if found is not None and found > 0:
        return found
    if scene_id == LISBON_SCENE_ID:
        return LISBON_CALIBRATION
    return None


def sigma0_db(dn: np.ndarray, factor: float) -> np.ndarray:
    """Calibrated sigma-nought in decibels. Non-positive samples become quiet."""

    linear = factor * np.square(dn.astype(np.float64))
    quiet = np.full(dn.shape, -99.0, dtype=np.float32)
    valid = linear > 0
    quiet[valid] = (10.0 * np.log10(linear[valid])).astype(np.float32)
    return quiet


def relative_db(dn: np.ndarray) -> np.ndarray:
    """Decibels of DN^2, for a display that must not be called sigma-nought."""

    return sigma0_db(dn, 1.0)


def pixel_metres(grid: Grid, scale: float) -> tuple[float, float]:
    """Ground size of one overview pixel, as (column metres, row metres)."""

    origin = grid.to_lonlat(0, 0, scale)
    column = metres(*origin, *grid.to_lonlat(1, 0, scale))
    row = metres(*origin, *grid.to_lonlat(0, 1, scale))
    return column, row


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def dwell_seconds(properties: dict[str, object]) -> float | None:
    start = properties.get("start_datetime")
    end = properties.get("end_datetime")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        span = (parse_time(end) - parse_time(start)).total_seconds()
    except ValueError:
        return None
    if span <= 0:
        return None
    return float(span)


def stretch(values: np.ndarray, low: float, high: float) -> np.ndarray:
    """Map a decibel image to 8-bit gray. The caller names low and high."""

    span = max(high - low, 1e-3)
    scaled = (values.astype(np.float32) - low) / span
    return cast(np.ndarray, np.clip(scaled, 0, 1))


def percentile_range(values: np.ndarray) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return -25.0, 0.0
    low, high = np.percentile(finite, [2, 98])
    if float(high) - float(low) < 1:
        high = float(low) + 1
    return float(low), float(high)


def _find_factor(value: object) -> float | None:
    if isinstance(value, dict):
        for key in _CALIBRATION_KEYS:
            found = _as_positive(value.get(key))
            if found is not None:
                return found
        for child in value.values():
            found = _find_factor(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_factor(child)
            if found is not None:
                return found
    return None


def _as_positive(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    return number
