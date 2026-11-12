"""Amplitude measurements on one overview grid.

Thresholds come from the scene histogram. A dark smooth component is open
water. A bright cluster on the land that remains is built-up return. A
long bright component on the waterline is a structure, not a named bridge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import numpy as np
from scipy import ndimage

# 3 dB is a factor of two. A 1-look intensity pixel has a spread of about
# 5.6 dB, so a 1.5 dB gate paints speckle. Patches smaller than
# CHANGE_SUPPORT pixels are dropped for the same reason.
CHANGE_DB = 3.0
CHANGE_SUPPORT = 8
# Land that is not at least this much brighter than the water mode cannot
# be split by brightness. The Tenerife strip spans about 0.35 dB.
WATER_GATE_DB = 1.5
# Wider than the 5-pixel speckle window, so a ridge survives averaging
# and calm water does not.
TEXTURE_WINDOW = 31
# Speckle gaps inside the water. An island or a city block is larger.
MAX_WATER_HOLE = 64


@dataclass(frozen=True)
class Component:
    area_m2: float
    length_m: float
    width_m: float
    row: float
    col: float
    peak_db: float
    mask: np.ndarray
    # (column, row) ends of the end-to-end axis. Compact returns leave this empty.
    ends: tuple[tuple[float, float], tuple[float, float]] | None = None


@dataclass(frozen=True)
class _Extent:
    """End-to-end axis of one component, in metres and in overview pixels."""

    length_m: float
    width_m: float
    ends: tuple[tuple[float, float], tuple[float, float]]
    centre_m: np.ndarray
    axis_m: np.ndarray
    proj_min: float
    proj_max: float


def water_mask(db: np.ndarray) -> tuple[np.ndarray, float]:
    """Dark, smooth, connected water and the decibel level of that dark peak.

    The peak is the darkest histogram mode, not the most common brightness.
    A land-majority scene would otherwise adopt the land level and paint
    the land as water. A dark smooth surface that is not water (shadow,
    tarmac, sand) still passes: the limit sentence says so.

    Two scenes were painting the whole frame. A winding river left the city
    blocks as holes, and filling every hole painted the blocks. Tenerife's
    smoothed strip spans a few tenths of a decibel, so the 1.5 dB gate
    already included the island; texture separates that sea from the ridges.
    """

    smooth = ndimage.uniform_filter(db, size=5)
    finite = smooth[np.isfinite(smooth)]
    if finite.size == 0:
        return np.zeros(db.shape, dtype=bool), -99.0
    mode = _dark_peak(finite)
    spread = float(np.percentile(finite, 90) - np.percentile(finite, 10))
    deviation = _local_deviation(db, smooth)
    near = np.abs(smooth - mode) <= WATER_GATE_DB
    speckle = float(np.median(deviation[near])) if np.any(near) else 1.0
    if not np.isfinite(speckle) or speckle <= 0:
        speckle = 1.0
    texture_limit = None
    if spread < WATER_GATE_DB:
        # Brightness cannot split this scene. Calm water stays smoother
        # than land once the window is wider than speckle.
        broad = ndimage.uniform_filter(db, size=TEXTURE_WINDOW)
        texture = _local_deviation(db, broad, TEXTURE_WINDOW)
        finite_texture = texture[np.isfinite(texture)]
        floor = (
            float(np.percentile(finite_texture, 20)) if finite_texture.size else 0.05
        )
        if not np.isfinite(floor) or floor <= 0:
            floor = 0.05
        texture_limit = floor * 2.0
        dark = (texture <= texture_limit) & np.isfinite(db)
        path = "texture"
    else:
        dark = (smooth <= mode + WATER_GATE_DB) & (deviation <= speckle * 2.0)
        dark &= np.isfinite(db)
        path = "brightness"
    large = _large_components(dark, 0.005)
    mask = _fill_small_holes(large, MAX_WATER_HOLE)
    # region agent log
    try:
        import json
        import time

        payload = {
            "sessionId": "2437e2",
            "timestamp": int(time.time() * 1000),
            "location": "measure.py:water_mask",
            "message": "water mask stages",
            "hypothesisId": "H-spread-and-holes",
            "runId": "post-fix",
            "data": {
                "shape": [int(db.shape[0]), int(db.shape[1])],
                "spread_db": round(spread, 4),
                "mode_db": round(float(mode), 4),
                "path": path,
                "speckle_db": round(speckle, 4),
                "texture_limit_db": None
                if texture_limit is None
                else round(float(texture_limit), 4),
                "frac_dark": round(float(dark.mean()), 4),
                "frac_large": round(float(large.mean()), 4),
                "frac_final": round(float(mask.mean()), 4),
                "holes_filled": int((mask & ~large).sum()),
            },
        }
        with open(
            "/home/gritter/Desktop/MainSideProjects/iceye-demo/.cursor/debug-2437e2.log",
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(json.dumps(payload) + "\n")
    except Exception:
        pass
    # endregion
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
    """The longest bright component along the water, when it is clearly long.

    Length is the end-to-end axis of the bright return. The 150 m band is
    where that return is found. A corridor may then follow the same axis
    past the band, and is kept only while the return stays thin.
    """

    pixel_m = min(col_m, row_m)
    if pixel_m <= 0:
        return None
    distance = ndimage.distance_transform_edt(~water) * pixel_m
    band = (distance > 0) & (distance <= 150) & (db >= mode_db + 6.0)
    band = ndimage.binary_closing(band, iterations=1)
    chosen = _longest(db, band, col_m, row_m, min_length_m=max(200.0, pixel_m * 40))
    if chosen is None:
        return None
    return _extend_corridor(db, chosen, mode_db, col_m, row_m)


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

    A difference under 3 dB is excluded from both masks, and so is a patch
    under 8 pixels. The picture is a separate ungated composite.
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


def _local_deviation(db: np.ndarray, smooth: np.ndarray, size: int = 5) -> np.ndarray:
    square = ndimage.uniform_filter(np.square(db), size=size)
    return cast(np.ndarray, np.sqrt(np.maximum(square - np.square(smooth), 0)))


def _fill_small_holes(mask: np.ndarray, max_pixels: int) -> np.ndarray:
    """Fill speckle holes. Leave a hole large enough to be land."""

    holes = ndimage.binary_fill_holes(mask) & ~mask
    labels, count = ndimage.label(holes)
    if count == 0:
        return mask
    sizes = np.bincount(labels.ravel())
    small = sizes <= max_pixels
    small[0] = False
    return cast(np.ndarray, mask | small[labels])


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
        extent = _end_to_end(rows, cols, row_m, col_m)
        if extent.length_m < min_length_m or extent.length_m < extent.width_m * 3:
            continue
        component = Component(
            area_m2=float(mask.sum()) * col_m * row_m,
            length_m=extent.length_m,
            width_m=extent.width_m,
            row=float(rows.mean()),
            col=float(cols.mean()),
            peak_db=float(np.nanmax(db[mask])),
            mask=mask,
            ends=extent.ends,
        )
        if best is None or component.length_m > best.length_m:
            best = component
    return best


def _end_to_end(
    rows: np.ndarray, cols: np.ndarray, row_m: float, col_m: float
) -> _Extent:
    """Principal-axis length, robust width, and the two (column, row) ends.

    Length is ``proj.max - proj.min`` of the pixel centres, not four standard
    deviations. Width is the 5th-to-95th percentile of the perpendicular.
    The ends sit half that length either side of the centre, so the segment
    and the reported length are the same distance.
    """

    coords = np.column_stack(
        [cols.astype(np.float64) * col_m, rows.astype(np.float64) * row_m]
    )
    centre = coords.mean(axis=0)
    spread = coords - centre
    cov = np.cov(spread, rowvar=False)
    values, vectors = np.linalg.eigh(cov)
    order = int(np.argmax(values))
    axis_m = np.asarray(vectors[:, order], dtype=np.float64)
    proj = spread @ axis_m
    length = float(proj.max() - proj.min())
    perp = spread @ np.array([-axis_m[1], axis_m[0]])
    width = float(np.percentile(perp, 95) - np.percentile(perp, 5))
    axis_col = float(axis_m[0]) / col_m
    axis_row = float(axis_m[1]) / row_m
    norm = float(np.hypot(axis_col, axis_row)) or 1.0
    axis_col /= norm
    axis_row /= norm
    centre_col = float(centre[0] / col_m)
    centre_row = float(centre[1] / row_m)
    step = float(np.hypot(axis_col * col_m, axis_row * row_m)) or 1.0
    span = (length / 2.0) / step
    ends = (
        (centre_col - axis_col * span, centre_row - axis_row * span),
        (centre_col + axis_col * span, centre_row + axis_row * span),
    )
    return _Extent(
        length,
        width,
        ends,
        centre,
        axis_m,
        float(proj.min()),
        float(proj.max()),
    )


def _extend_corridor(
    db: np.ndarray,
    component: Component,
    mode_db: float,
    col_m: float,
    row_m: float,
) -> Component:
    """Walk the axis past the shoreline band and keep the run only if it stays thin.

    The window is a quarter of the mask width, the bright core rather than
    the whole layover return. Each direction stops at a dark gap longer than
    one closing iteration (``2 * pixel_m``) or at 500 m. Past that the
    approach is still bright and the line leaves the deck. When both ends
    are bright, only the longer run is kept: the short run is clutter at
    the anchorage and pulls the axis off the return.
    """

    rows, cols = np.nonzero(component.mask)
    extent = _end_to_end(rows, cols, row_m, col_m)
    extra = _corridor_pixels(db, extent, mode_db + 6.0, col_m, row_m)
    if not np.any(extra):
        return component
    union = component.mask | extra
    grown_rows, grown_cols = np.nonzero(union)
    grown = _end_to_end(grown_rows, grown_cols, row_m, col_m)
    if grown.length_m < grown.width_m * 3:
        return component
    return Component(
        area_m2=float(union.sum()) * col_m * row_m,
        length_m=grown.length_m,
        width_m=grown.width_m,
        row=float(grown_rows.mean()),
        col=float(grown_cols.mean()),
        peak_db=float(np.nanmax(db[union])),
        mask=union,
        ends=grown.ends,
    )


def _corridor_pixels(
    db: np.ndarray,
    extent: _Extent,
    gate_db: float,
    col_m: float,
    row_m: float,
) -> np.ndarray:
    """Bright pixels beyond the ends, along the longer core of the return."""

    extra = np.zeros(db.shape, dtype=bool)
    pixel_m = min(col_m, row_m)
    if pixel_m <= 0:
        return extra
    axis = extent.axis_m
    perp = np.array([-axis[1], axis[0]], dtype=np.float64)
    # One closing iteration bridges about two pixels. A longer dark run stops.
    gap_m = 2.0 * pixel_m
    # 600 m still follows the bright approach off the deck. 500 m covers the
    # piece the 150 m band cuts off and stays on the return.
    cap_m = 500.0
    half_m = max(extent.width_m / 4.0, pixel_m)
    arms: list[tuple[float, list[tuple[int, int]]]] = []
    for direction, edge in ((1.0, extent.proj_max), (-1.0, extent.proj_min)):
        travelled = 0.0
        dark = 0.0
        reached = 0.0
        accepted: list[tuple[int, int]] = []
        while travelled < cap_m:
            travelled += pixel_m
            if travelled > cap_m:
                break
            origin = extent.centre_m + axis * (edge + direction * travelled)
            hits = _bright_slice(
                db, origin, axis, perp, half_m, pixel_m, col_m, row_m, gate_db
            )
            if hits:
                dark = 0.0
                reached = travelled
                accepted.extend(hits)
            else:
                dark += pixel_m
                if dark > gap_m:
                    break
        arms.append((reached, accepted))
    longer = max(arms, key=lambda arm: arm[0])
    for row, col in longer[1]:
        extra[row, col] = True
    return extra


def _bright_slice(
    db: np.ndarray,
    origin: np.ndarray,
    axis: np.ndarray,
    perp: np.ndarray,
    half_m: float,
    pixel_m: float,
    col_m: float,
    row_m: float,
    gate_db: float,
) -> list[tuple[int, int]]:
    """Pixels in this station's corridor window that clear the brightness gate."""

    along_limit = pixel_m / 2.0
    pad_m = max(half_m, along_limit) + max(col_m, row_m)
    rad_col = int(math.ceil(pad_m / col_m)) + 1
    rad_row = int(math.ceil(pad_m / row_m)) + 1
    centre_col = float(origin[0] / col_m)
    centre_row = float(origin[1] / row_m)
    col0 = max(0, int(math.floor(centre_col)) - rad_col)
    col1 = min(int(db.shape[1]), int(math.ceil(centre_col)) + rad_col + 1)
    row0 = max(0, int(math.floor(centre_row)) - rad_row)
    row1 = min(int(db.shape[0]), int(math.ceil(centre_row)) + rad_row + 1)
    if row0 >= row1 or col0 >= col1:
        return []
    window = db[row0:row1, col0:col1]
    rows = np.arange(row0, row1)
    cols = np.arange(col0, col1)
    grid_cols, grid_rows = np.meshgrid(cols, rows)
    rel_x = grid_cols.astype(np.float64) * col_m - float(origin[0])
    rel_y = grid_rows.astype(np.float64) * row_m - float(origin[1])
    along = rel_x * float(axis[0]) + rel_y * float(axis[1])
    across = rel_x * float(perp[0]) + rel_y * float(perp[1])
    bright = (
        (np.abs(along) <= along_limit + 1e-6)
        & (np.abs(across) <= half_m + 1e-6)
        & np.isfinite(window)
        & (window >= gate_db)
    )
    hit_rows, hit_cols = np.nonzero(bright)
    return list(
        zip((hit_rows + row0).tolist(), (hit_cols + col0).tolist(), strict=True)
    )


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
