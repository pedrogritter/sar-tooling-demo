"""Amplitude measurements on one overview grid.

Thresholds come from the scene histogram. A dark smooth component is open
water. A bright cluster on the land that remains is built-up return. A
long bright component on the waterline is a structure, not a named bridge.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
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
# 0.0005 of a frame of 1 m pixels. Dividing by the overview pixel area
# keeps that ground area when the loaded overview is coarser than 1 m.
BUILT_UP_AREA_FRACTION = 0.0005
# The 1.5 dB gate stays inside this incidence band. Outside it, sea
# brightness has already moved by about 1 dB per degree, so the gate
# widens by half a decibel per degree and then stops at the control max.
_INCIDENCE_LOW = 26.0
_INCIDENCE_HIGH = 34.0
_INCIDENCE_DB_PER_DEGREE = 0.5


@dataclass(frozen=True)
class Control:
    """One number the sidebar can move. ``suggest`` is how the scene fills it.

    ``incidence`` applies only when ``default`` is 1.5 dB. ``pixel`` keeps a
    window near ``default`` metres on the ground. ``none`` keeps ``default``.
    """

    id: str
    label: str
    unit: str
    minimum: float
    maximum: float
    step: float
    default: float
    suggest: str


class ControlError(ValueError):
    """The job body named an unknown control or a number outside its range."""


def _control(
    control_id: str,
    label: str,
    unit: str,
    minimum: float,
    maximum: float,
    step: float,
    default: float,
    suggest: str = "none",
) -> Control:
    return Control(
        control_id, label, unit, minimum, maximum, step, default, suggest
    )


# Shared objects so two tools cannot drift apart on a gate they both state.
_WATER_GATE = _control(
    "water_gate_db", "Water gate", "dB", 0.5, 4, 0.1, WATER_GATE_DB, "incidence"
)
_TEXTURE_WINDOW = _control(
    "texture_window_px",
    "Texture window",
    "px",
    5,
    61,
    1,
    TEXTURE_WINDOW,
    "pixel",
)
_MAX_HOLE = _control(
    "max_hole_px", "Largest hole filled", "px", 8, 256, 1, MAX_WATER_HOLE, "pixel"
)
_SPLIT = _control(
    "split_db", "Roughness split", "dB", 0.5, 4, 0.1, 1.5, "incidence"
)
_BRIGHT_8 = _control("bright_offset_db", "Bright offset", "dB", 4, 16, 0.1, 8)
_BRIGHT_6 = _control("bright_offset_db", "Bright offset", "dB", 3, 12, 0.1, 6)
_MIN_AREA = _control("min_area_m2", "Minimum area", "m²", 4, 200, 1, 20)
_BAND = _control("band_m", "Shore band", "m", 50, 400, 1, 150)
_MIN_LENGTH = _control("min_length_m", "Minimum length", "m", 50, 1000, 1, 200)
_SEARCH = _control(
    "search_radius_px", "Search radius", "px", 2, 20, 1, 6, "pixel"
)
_MOVE = _control("move_gate_m", "Move gate", "m", 5, 100, 1, 20)
_CHANGE = _control("change_db", "Change gate", "dB", 1, 8, 0.1, CHANGE_DB)
_CHANGE_SUPPORT = _control(
    "support_px", "Minimum patch", "px", 4, 64, 1, CHANGE_SUPPORT, "pixel"
)
# Same range as the change patch, but this one does not follow pixel size.
_DARK_SUPPORT = _control("support_px", "Minimum patch", "px", 4, 64, 1, 8)
_DARK = _control("dark_db", "Dark gate", "dB", 1, 6, 0.1, 2)
_RING = _control("ring_db", "Ring contrast", "dB", 0.5, 4, 0.1, 1)
_SHORE = _control("width_px", "Shoreline width", "px", 1, 5, 1, 1)
_MATCH = _control("match_m", "Match distance", "m", 20, 300, 1, 80)
_MIN_PIXELS = _control("min_pixels", "Minimum cluster", "px", 2, 32, 1, 4)

TOOL_CONTROLS: dict[str, tuple[Control, ...]] = {
    "open-water": (_WATER_GATE, _TEXTURE_WINDOW, _MAX_HOLE),
    "sea-roughness": (_SPLIT,),
    "built-up": (_BRIGHT_8,),
    "returns-on-water": (_BRIGHT_8, _MIN_AREA),
    "long-structure": (_BAND, _BRIGHT_6, _MIN_LENGTH),
    "dwell-motion": (_SEARCH, _MOVE),
    "amplitude-change": (_CHANGE, _CHANGE_SUPPORT),
    "water-persistence": (_WATER_GATE,),
    "sea-state": (_WATER_GATE,),
    "dark-sea-anomaly": (_DARK, _DARK_SUPPORT, _RING),
    "shoreline-series": (_SHORE,),
    "date-of-change": (_CHANGE, _CHANGE_SUPPORT),
    "repeat-returns": (_MATCH,),
    "site-activity": (_BRIGHT_8, _MIN_PIXELS),
    "stack-mean": (),
}


def suggested_value(
    spec: Control, incidence: float | None, pixel_m: float | None
) -> float:
    """The number an omitted key uses for this scene."""

    if spec.suggest == "incidence" and spec.default == 1.5:
        return _suggest_incidence(spec.default, incidence, spec.maximum)
    if spec.suggest == "pixel":
        return _suggest_pixels(spec.default, pixel_m, spec.minimum, spec.maximum)
    return spec.default


def _suggest_incidence(
    default: float, incidence: float | None, maximum: float
) -> float:
    """Keep 1.5 dB inside 26–34°. Add 0.5 dB per degree outside, then clamp."""

    if incidence is None or not math.isfinite(incidence):
        return default
    if _INCIDENCE_LOW <= incidence <= _INCIDENCE_HIGH:
        return default
    if incidence < _INCIDENCE_LOW:
        beyond = _INCIDENCE_LOW - incidence
    else:
        beyond = incidence - _INCIDENCE_HIGH
    widened = default + _INCIDENCE_DB_PER_DEGREE * beyond
    return min(widened, maximum)


def _suggest_pixels(
    default_px: float, pixel_m: float | None, low: float, high: float
) -> float:
    """Odd window nearest to ``default_px / pixel_m``, clamped to the range.

    Missing overview metres keep ``default_px``, even when that default is
    even. The ground length of the window then stays near ``default_px`` metres.
    """

    if pixel_m is None or not math.isfinite(pixel_m) or pixel_m <= 0:
        return default_px
    odd = _nearest_odd(default_px / pixel_m)
    clamped = min(max(float(odd), low), high)
    return float(round(clamped))


def _nearest_odd(value: float) -> int:
    """Odd integer closest to ``value``. An exact tie uses the lower odd."""

    lower = math.floor(value)
    if lower % 2 == 0:
        left = lower - 1
        right = lower + 1
    else:
        left = lower
        right = lower + 2
    if abs(value - left) <= abs(value - right):
        return int(left)
    return int(right)


def resolve_controls(
    tool_id: str,
    overrides: Mapping[str, float] | None,
    incidence: float | None,
    pixel_m: float | None,
) -> dict[str, float]:
    """Use an override when the body sent it, otherwise the scene suggestion."""

    provided = {} if overrides is None else overrides
    resolved: dict[str, float] = {}
    for spec in TOOL_CONTROLS[tool_id]:
        if spec.id in provided:
            resolved[spec.id] = float(provided[spec.id])
        else:
            resolved[spec.id] = suggested_value(spec, incidence, pixel_m)
    return resolved


def catalog_defaults(tool_id: str) -> dict[str, float]:
    """The numbers written into today's sentences, before a scene moves them."""

    return {spec.id: spec.default for spec in TOOL_CONTROLS[tool_id]}


def control_payloads(
    tool_id: str, incidence: float | None, pixel_m: float | None
) -> tuple[dict[str, object], ...]:
    """Sidebar fields. ``value`` is the suggestion for this scene."""

    return tuple(
        _control_public(spec, suggested_value(spec, incidence, pixel_m))
        for spec in TOOL_CONTROLS[tool_id]
    )


def parse_control_overrides(tool_id: str, raw: object) -> dict[str, float]:
    """Overrides from a job body. A missing object means no overrides.

    An unknown key, a non-number, or a number outside the control's range
    raises ``ControlError``. Pixel controls have to be whole numbers.
    """

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ControlError("controls must be an object.")
    specs = {spec.id: spec for spec in TOOL_CONTROLS[tool_id]}
    parsed: dict[str, float] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or key not in specs:
            name = key if isinstance(key, str) else "controls"
            raise ControlError(f"Unknown control {name}.")
        parsed[key] = _control_number(specs[key], value)
    return parsed


def _control_number(spec: Control, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ControlError(
            f"{spec.id} must be a number from {spec.minimum:g} to {spec.maximum:g}."
        )
    number = float(value)
    if not math.isfinite(number) or number < spec.minimum or number > spec.maximum:
        raise ControlError(
            f"{spec.id} must be from {spec.minimum:g} to {spec.maximum:g}."
        )
    if spec.unit == "px" and not number.is_integer():
        raise ControlError(
            f"{spec.id} must be a whole number "
            f"from {spec.minimum:g} to {spec.maximum:g}."
        )
    return number


def _control_public(spec: Control, value: float) -> dict[str, object]:
    return {
        "id": spec.id,
        "label": spec.label,
        "unit": spec.unit,
        "min": _public_number(spec.minimum),
        "max": _public_number(spec.maximum),
        "step": _public_number(spec.step),
        "value": _public_number(value),
    }


def _public_number(value: float) -> int | float:
    if float(value).is_integer():
        return int(value)
    return float(value)


def _built_up_fraction(col_m: float, row_m: float) -> float:
    """Pixel fraction whose ground area is 0.0005 of a 1 m pixel frame."""

    pixel_area = col_m * row_m
    if not math.isfinite(pixel_area) or pixel_area <= 0:
        pixel_area = 1.0
    return BUILT_UP_AREA_FRACTION / pixel_area


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


def water_mask(
    db: np.ndarray,
    *,
    water_gate_db: float = WATER_GATE_DB,
    texture_window_px: int = TEXTURE_WINDOW,
    max_hole_px: int = MAX_WATER_HOLE,
) -> tuple[np.ndarray, float]:
    """Dark, smooth, connected water and the decibel level of that dark peak.

    The peak is the darkest histogram mode, not the most common brightness.
    A land-majority scene would otherwise adopt the land level and paint
    the land as water. A dark smooth surface that is not water (shadow,
    tarmac, sand) still passes: the limit sentence says so.

    Two scenes were painting the whole frame. A winding river left the city
    blocks as holes, and filling every hole painted the blocks. Tenerife's
    smoothed strip spans a few tenths of a decibel, so the gate already
    included the island; texture separates that sea from the ridges.
    ``water_gate_db`` is that brightness gate. ``texture_window_px`` is the
    window used when brightness cannot split the scene. ``max_hole_px`` is
    the largest hole still filled as speckle.
    """

    smooth = ndimage.uniform_filter(db, size=5)
    finite = smooth[np.isfinite(smooth)]
    if finite.size == 0:
        return np.zeros(db.shape, dtype=bool), -99.0
    mode = _dark_peak(finite)
    spread = float(np.percentile(finite, 90) - np.percentile(finite, 10))
    deviation = _local_deviation(db, smooth)
    near = np.abs(smooth - mode) <= water_gate_db
    speckle = float(np.median(deviation[near])) if np.any(near) else 1.0
    if not np.isfinite(speckle) or speckle <= 0:
        speckle = 1.0
    window = max(int(texture_window_px), 1)
    if spread < water_gate_db:
        # Brightness cannot split this scene. Calm water stays smoother
        # than land once the window is wider than speckle.
        broad = ndimage.uniform_filter(db, size=window)
        texture = _local_deviation(db, broad, window)
        finite_texture = texture[np.isfinite(texture)]
        floor = (
            float(np.percentile(finite_texture, 20)) if finite_texture.size else 0.05
        )
        if not np.isfinite(floor) or floor <= 0:
            floor = 0.05
        # A wider texture window raises this floor on a ridge and leaves
        # calm water under it. The gate above decides which path runs.
        texture_limit = floor * 2.0
        dark = (texture <= texture_limit) & np.isfinite(db)
    else:
        dark = (smooth <= mode + water_gate_db) & (deviation <= speckle * 2.0)
        dark &= np.isfinite(db)
    large = _large_components(dark, 0.005)
    mask = _fill_small_holes(large, int(max_hole_px))
    return mask, mode


def split_roughness(
    db: np.ndarray, water: np.ndarray, *, split_db: float = 1.5
) -> tuple[np.ndarray, np.ndarray, str]:
    """Split water into calm and wind-roughened. A flat sea stays one class.

    The 10th-to-90th spread is the first gate. After a median cut, halves
    whose medians differ by less than ``split_db`` are still one sea: the
    spread was the tails, not two classes. The split is not a wave height.
    """

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
    gate = f"{split_db:g}"
    if spread < split_db:
        return (
            water.copy(),
            rough,
            f"The water spans less than {gate} dB, so it is drawn as one class.",
        )
    middle = float(np.median(values))
    calm = water & (db <= middle)
    rough = water & (db > middle)
    calm_values = db[calm]
    rough_values = db[rough]
    if calm_values.size and rough_values.size:
        calm_median = float(np.median(calm_values))
        rough_median = float(np.median(rough_values))
        # A gap under the split is not a wind split.
        if abs(calm_median - rough_median) < split_db:
            return (
                water.copy(),
                np.zeros(db.shape, dtype=bool),
                f"The two classes differ by less than {gate} dB, "
                "so the water is drawn as one class.",
            )
    return calm, rough, f"The split is the median water return, {middle:.1f} dB."


def built_up_mask(
    db: np.ndarray,
    water: np.ndarray,
    mode_db: float,
    *,
    bright_offset_db: float = 8.0,
    col_m: float = 1.0,
    row_m: float = 1.0,
) -> np.ndarray:
    """Bright clusters on land. Water is excluded so a hull is not a building.

    ``bright_offset_db`` is how far above the water mode a land pixel must
    sit. The minimum cluster is a ground area, not a fraction of the
    overview that happened to be loaded.
    """

    bright = np.isfinite(db) & ~water & (db >= mode_db + bright_offset_db)
    return _large_components(bright, _built_up_fraction(col_m, row_m))


def long_structure(
    db: np.ndarray,
    water: np.ndarray,
    mode_db: float,
    col_m: float,
    row_m: float,
    *,
    band_m: float = 150.0,
    bright_offset_db: float = 6.0,
    min_length_m: float = 200.0,
) -> Component | None:
    """The longest bright component along the water, when it is clearly long.

    Length is the end-to-end axis of the bright return. ``band_m`` is where
    that return is found. A corridor may then follow the same axis past the
    band, and is kept only while the return stays thin. The length still
    has to clear forty overview pixels, so a coarse pixel cannot report a
    short streak as a long structure.
    """

    pixel_m = min(col_m, row_m)
    if pixel_m <= 0:
        return None
    distance = ndimage.distance_transform_edt(~water) * pixel_m
    band = (distance > 0) & (distance <= band_m) & (db >= mode_db + bright_offset_db)
    band = ndimage.binary_closing(band, iterations=1)
    floor_m = max(min_length_m, pixel_m * 40)
    chosen = _longest(db, band, col_m, row_m, min_length_m=floor_m)
    if chosen is None:
        return None
    return _extend_corridor(
        db, chosen, mode_db, col_m, row_m, bright_offset_db=bright_offset_db
    )


def waterline_returns(
    db: np.ndarray,
    water: np.ndarray,
    mode_db: float,
    col_m: float,
    row_m: float,
    excluded: np.ndarray | None = None,
    *,
    bright_offset_db: float = 8.0,
    min_area_m2: float = 20.0,
) -> list[Component]:
    """Compact bright components that touch the water.

    A component counts when at least one pixel is within one overview pixel
    of the water mask. The brightest 24 are a last bound after that test,
    not the test that drops the hillside. Four overview pixels remain the
    area floor, so ``min_area_m2`` cannot count a smaller patch.
    """

    pixel_m = max(min(col_m, row_m), 1e-3)
    distance = ndimage.distance_transform_edt(~water) * pixel_m
    bright = (db >= mode_db + bright_offset_db) & np.isfinite(db)
    if excluded is not None:
        bright &= ~excluded
    labels, count = ndimage.label(bright)
    found: list[Component] = []
    # Four overview pixels is the floor under whatever area the control set.
    minimum = max(min_area_m2, pixel_m * pixel_m * 4)
    for index, window in enumerate(ndimage.find_objects(labels), start=1):
        if window is None or index > count:
            continue
        mask = np.zeros(db.shape, dtype=bool)
        local = labels[window] == index
        mask[window] = local
        # Metres inland from the water. One overview pixel is the touch test.
        if not np.any(distance[mask] <= pixel_m):
            continue
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
    *,
    search_radius_px: int = 6,
    move_gate_m: float = 20.0,
) -> list[dict[str, object]]:
    """Follow each centre across the dwell. Displacement uses the first and last hit.

    Every frame is searched in the window around the original centre.
    Recentering on the peak crawls along a bright ridge and paints that
    ridge as motion. A track is moved only when first-to-last displacement
    clears the gate. Four overview pixels remain the floor under that gate.
    """

    frames = int(video.shape[0])
    radius = int(search_radius_px)
    tracks: list[dict[str, object]] = []
    for row, col in centres:
        origin_row = row * row_scale
        origin_col = col * col_scale
        points: list[tuple[float, float]] = []
        for index in range(frames):
            r0 = max(0, int(origin_row) - radius)
            r1 = min(int(video.shape[1]), int(origin_row) + radius + 1)
            c0 = max(0, int(origin_col) - radius)
            c1 = min(int(video.shape[2]), int(origin_col) + radius + 1)
            window = video[index, r0:r1, c0:c1]
            if window.size == 0:
                continue
            peak = np.unravel_index(int(np.argmax(window)), window.shape)
            hit_row = r0 + float(peak[0])
            hit_col = c0 + float(peak[1])
            points.append((hit_row / row_scale, hit_col / col_scale))
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
        moved = displacement >= max(move_gate_m, pixel_m * 4)
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
    earlier: np.ndarray,
    later: np.ndarray,
    *,
    change_db: float = CHANGE_DB,
    support_px: int = CHANGE_SUPPORT,
) -> tuple[np.ndarray, np.ndarray]:
    """Later-darker and later-brighter masks.

    A difference under ``change_db`` is excluded from both masks, and so is
    a patch under ``support_px`` pixels. The picture is a separate ungated
    composite, so it may still colour a weaker difference than these counts.
    """

    delta = later - earlier
    valid = np.isfinite(earlier) & np.isfinite(later)
    darker = valid & (delta <= -change_db)
    brighter = valid & (delta >= change_db)
    support = int(support_px)
    return _supported(darker, support), _supported(brighter, support)


def _supported(mask: np.ndarray, support_px: int = CHANGE_SUPPORT) -> np.ndarray:
    """Drop a change patch smaller than ``support_px`` pixels."""

    labels, count = ndimage.label(mask)
    if count == 0:
        return np.zeros(mask.shape, dtype=bool)
    counts = np.bincount(labels.ravel())
    keep = counts >= support_px
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
    *,
    bright_offset_db: float = 6.0,
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
    extra = _corridor_pixels(db, extent, mode_db + bright_offset_db, col_m, row_m)
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
