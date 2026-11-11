"""Amplitude measurements on one overview grid.

Thresholds come from the scene histogram. A dark smooth component is open
water. A bright cluster on the land that remains is built-up return. A
long bright component on the waterline is a structure, not a named bridge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
from scipy import ndimage

# 3 dB is a factor of two. A 1-look intensity pixel has a spread of about
# 5.6 dB, so a 1.5 dB gate paints speckle. Patches smaller than
# CHANGE_SUPPORT pixels are dropped for the same reason.
CHANGE_DB = 3.0
CHANGE_SUPPORT = 8


@dataclass(frozen=True)
class Component:
    area_m2: float
    length_m: float
    width_m: float
    row: float
    col: float
    peak_db: float
    mask: np.ndarray


def water_mask(db: np.ndarray) -> tuple[np.ndarray, float]:
    """Dark, smooth, connected water and the decibel level of that dark peak.

    The peak is the darkest histogram mode, not the most common brightness.
    A land-majority scene would otherwise adopt the land level and paint
    the land as water. A dark smooth surface that is not water (shadow,
    tarmac, sand) still passes: the limit sentence says so.
    """

    smooth = ndimage.uniform_filter(db, size=5)
    finite = smooth[np.isfinite(smooth)]
    if finite.size == 0:
        return np.zeros(db.shape, dtype=bool), -99.0
    mode = _dark_peak(finite)
    deviation = _local_deviation(db, smooth)
    near = np.abs(smooth - mode) <= 1.5
    speckle = float(np.median(deviation[near])) if np.any(near) else 1.0
    if not np.isfinite(speckle) or speckle <= 0:
        speckle = 1.0
    dark = (smooth <= mode + 1.5) & (deviation <= speckle * 2.0) & np.isfinite(db)
    mask = _large_components(dark, 0.005)
    mask = ndimage.binary_fill_holes(mask)
    return mask, mode


def split_roughness(
    db: np.ndarray, water: np.ndarray
) -> tuple[np.ndarray, np.ndarray, str]:
    """Split water into calm and wind-roughened. A flat sea stays one class."""

    calm = np.zeros(db.shape, dtype=bool)
    rough = np.zeros(db.shape, dtype=bool)
    values = db[water & np.isfinite(db)]
    if values.size == 0:
        return (
            calm,
            rough,
            "The water mask is empty, so there is no sea state to split.",
        )
    spread = float(np.percentile(values, 90) - np.percentile(values, 10))
    if spread < 1.5:
        return (
            water.copy(),
            rough,
            "The water spans less than 1.5 dB, so it is drawn as one class.",
        )
    middle = float(np.median(values))
    calm = water & (db <= middle)
    rough = water & (db > middle)
    return calm, rough, f"The split is the median water return, {middle:.1f} dB."


def built_up_mask(db: np.ndarray, water: np.ndarray, mode_db: float) -> np.ndarray:
    """Bright clusters on land. Water is excluded so a hull is not a building."""

    bright = np.isfinite(db) & ~water & (db >= mode_db + 8.0)
    return _large_components(bright, 0.0005)


def long_structure(
    db: np.ndarray,
    water: np.ndarray,
    mode_db: float,
    col_m: float,
    row_m: float,
) -> Component | None:
    """The longest bright component along the water, when it is clearly long."""

    pixel_m = min(col_m, row_m)
    if pixel_m <= 0:
        return None
    distance = ndimage.distance_transform_edt(~water) * pixel_m
    band = (distance > 0) & (distance <= 150) & (db >= mode_db + 6.0)
    band = ndimage.binary_closing(band, iterations=1)
    return _longest(db, band, col_m, row_m, min_length_m=max(200.0, pixel_m * 40))


def waterline_returns(
    db: np.ndarray,
    water: np.ndarray,
    mode_db: float,
    col_m: float,
    row_m: float,
    excluded: np.ndarray | None = None,
) -> list[Component]:
    """Compact bright components that touch the water."""

    pixel_m = max(min(col_m, row_m), 1e-3)
    distance = ndimage.distance_transform_edt(~water) * pixel_m
    bright = (db >= mode_db + 8.0) & (distance <= 80) & np.isfinite(db)
    if excluded is not None:
        bright &= ~excluded
    labels, count = ndimage.label(bright)
    found: list[Component] = []
    minimum = max(20.0, pixel_m * pixel_m * 4)
    for index, window in enumerate(ndimage.find_objects(labels), start=1):
        if window is None or index > count:
            continue
        mask = np.zeros(db.shape, dtype=bool)
        local = labels[window] == index
        mask[window] = local
        area = float(mask.sum()) * col_m * row_m
        if area < minimum:
            continue
        rows, cols = np.nonzero(mask)
        length_m, width_m = _axis_lengths(rows, cols, row_m, col_m)
        centre_row = float(rows.mean())
        centre_col = float(cols.mean())
        found.append(
            Component(
                area_m2=area,
                length_m=length_m,
                width_m=width_m,
                row=centre_row,
                col=centre_col,
                peak_db=float(np.nanmax(db[mask])),
                mask=mask,
            )
        )
    found.sort(key=lambda item: item.peak_db, reverse=True)
    return found[:24]


def track_returns(
    video: np.ndarray,
    centres: list[tuple[float, float]],
    row_scale: float,
    col_scale: float,
    pixel_m: float,
    dwell_s: float,
) -> list[dict[str, object]]:
    """Follow each centre across the dwell. Displacement uses the first and last hit."""

    frames = int(video.shape[0])
    radius = 6
    tracks: list[dict[str, object]] = []
    for row, col in centres:
        current_row = row * row_scale
        current_col = col * col_scale
        points: list[tuple[float, float]] = []
        for index in range(frames):
            r0 = max(0, int(current_row) - radius)
            r1 = min(int(video.shape[1]), int(current_row) + radius + 1)
            c0 = max(0, int(current_col) - radius)
            c1 = min(int(video.shape[2]), int(current_col) + radius + 1)
            window = video[index, r0:r1, c0:c1]
            if window.size == 0:
                continue
            peak = np.unravel_index(int(np.argmax(window)), window.shape)
            current_row = r0 + float(peak[0])
            current_col = c0 + float(peak[1])
            points.append((current_row / row_scale, current_col / col_scale))
        if len(points) < 2:
            tracks.append(
                {
                    "points": points,
                    "displacement_m": 0.0,
                    "speed_m_s": 0.0,
                    "motion": "not tracked",
                }
            )
            continue
        start, end = points[0], points[-1]
        displacement = float(
            np.hypot((end[0] - start[0]) * pixel_m, (end[1] - start[1]) * pixel_m)
        )
        moved = displacement >= max(8.0, pixel_m * 2)
        speed = displacement / dwell_s if dwell_s > 0 else 0.0
        tracks.append(
            {
                "points": points,
                "displacement_m": round(displacement, 1),
                "speed_m_s": round(speed, 2),
                "motion": "moved" if moved else "stationary during the dwell",
            }
        )
    return tracks


def change_masks(
    earlier: np.ndarray, later: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Later-darker and later-brighter masks.

    A difference under 3 dB stays gray, and so does a patch under 8 pixels.
    """

    delta = later - earlier
    valid = np.isfinite(earlier) & np.isfinite(later)
    darker = valid & (delta <= -CHANGE_DB)
    brighter = valid & (delta >= CHANGE_DB)
    return _supported(darker), _supported(brighter)


def _supported(mask: np.ndarray) -> np.ndarray:
    """Drop a change patch smaller than ``CHANGE_SUPPORT`` pixels."""

    labels, count = ndimage.label(mask)
    if count == 0:
        return np.zeros(mask.shape, dtype=bool)
    counts = np.bincount(labels.ravel())
    keep = counts >= CHANGE_SUPPORT
    keep[0] = False
    return cast(np.ndarray, keep[labels])


def _dark_peak(values: np.ndarray) -> float:
    """Centre of the darkest histogram mode that holds at least 0.5 percent."""

    low = float(np.percentile(values, 1))
    high = float(np.percentile(values, 99))
    if high <= low:
        return float(np.median(values))
    hist, edges = np.histogram(values, bins=64, range=(low, high))
    minimum = 0.005 * float(values.size)
    for index, count in enumerate(hist):
        left = hist[index - 1] if index else -1
        right = hist[index + 1] if index + 1 < hist.size else -1
        if count >= left and count >= right and count >= minimum:
            return float((edges[index] + edges[index + 1]) / 2)
    peak = int(np.argmax(hist))
    return float((edges[peak] + edges[peak + 1]) / 2)


def _local_deviation(db: np.ndarray, smooth: np.ndarray) -> np.ndarray:
    square = ndimage.uniform_filter(np.square(db), size=5)
    return cast(np.ndarray, np.sqrt(np.maximum(square - np.square(smooth), 0)))


def _large_components(mask: np.ndarray, minimum_fraction: float) -> np.ndarray:
    labels, count = ndimage.label(mask)
    if count == 0:
        return np.zeros(mask.shape, dtype=bool)
    counts = np.bincount(labels.ravel())
    keep = counts >= minimum_fraction * mask.size
    keep[0] = False
    return cast(np.ndarray, keep[labels])


def _longest(
    db: np.ndarray,
    band: np.ndarray,
    col_m: float,
    row_m: float,
    min_length_m: float,
) -> Component | None:
    labels, count = ndimage.label(band)
    best: Component | None = None
    for index in range(1, count + 1):
        mask = labels == index
        rows, cols = np.nonzero(mask)
        if rows.size < 8:
            continue
        length_m, width_m = _axis_lengths(rows, cols, row_m, col_m)
        if length_m < min_length_m or length_m < width_m * 3:
            continue
        component = Component(
            area_m2=float(mask.sum()) * col_m * row_m,
            length_m=length_m,
            width_m=width_m,
            row=float(rows.mean()),
            col=float(cols.mean()),
            peak_db=float(np.nanmax(db[mask])),
            mask=mask,
        )
        if best is None or component.length_m > best.length_m:
            best = component
    return best


def _axis_lengths(
    rows: np.ndarray, cols: np.ndarray, row_m: float, col_m: float
) -> tuple[float, float]:
    y = rows.astype(np.float64) * row_m
    x = cols.astype(np.float64) * col_m
    y -= y.mean()
    x -= x.mean()
    cov = np.cov(np.vstack([y, x]))
    if cov.ndim < 2:
        return 0.0, 0.0
    vals = np.linalg.eigvalsh(cov)
    length = 4 * float(np.sqrt(max(float(vals[-1]), 0.0)))
    width = 4 * float(np.sqrt(max(float(vals[0]), 0.0)))
    return length, max(width, min(row_m, col_m))
