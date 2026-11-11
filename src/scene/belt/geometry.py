"""Match two collects when a change or a stack is allowed to compare them."""

from __future__ import annotations

from dataclasses import dataclass

from scene.grid import Grid

CALIBRATED_MODES = frozenset({"spotlight", "stripmap"})
# X-band VV sea sigma-nought can fall by about a decibel per degree of
# incidence between 26° and 34°. A wider window would look like change.
INCIDENCE_TOLERANCE = 1.0
MIN_OVERLAP = 0.3


@dataclass(frozen=True)
class Collect:
    """Geometry and files the belt needs from one scene folder."""

    scene_id: str
    collected_at: str
    mode: str
    orbit: str
    look: str
    incidence: float
    bbox: tuple[float, float, float, float]
    has_grd: bool
    has_vid: bool
    calibrated: bool


def is_calibrated_mode(mode: str) -> bool:
    return mode in CALIBRATED_MODES


def overlap_fraction(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    """Intersection area divided by the smaller footprint. Zero when disjoint."""

    west = max(left[0], right[0])
    south = max(left[1], right[1])
    east = min(left[2], right[2])
    north = min(left[3], right[3])
    if east <= west or north <= south:
        return 0.0
    shared = (east - west) * (north - south)
    left_area = max((left[2] - left[0]) * (left[3] - left[1]), 1e-12)
    right_area = max((right[2] - right[0]) * (right[3] - right[1]), 1e-12)
    return shared / min(left_area, right_area)


def same_look(left: Collect, right: Collect) -> bool:
    """True when orbit, look side, and incidence are close enough to compare."""

    if not left.orbit or not right.orbit or left.orbit != right.orbit:
        return False
    if not left.look or not right.look or left.look != right.look:
        return False
    return abs(left.incidence - right.incidence) <= INCIDENCE_TOLERANCE


def can_pair(left: Collect, right: Collect) -> bool:
    if left.scene_id == right.scene_id:
        return False
    if not (left.calibrated and right.calibrated and left.has_grd and right.has_grd):
        return False
    if not same_look(left, right):
        return False
    return overlap_fraction(left.bbox, right.bbox) >= MIN_OVERLAP


def warp_affine(
    values: object,
    source: Grid,
    source_scale: float,
    shape: tuple[int, int],
    dest: Grid,
    dest_scale: float,
) -> object:
    """Resample ``values`` onto the destination overview grid. Outside is NaN."""

    import numpy as np
    from scipy.ndimage import map_coordinates

    grid = np.asarray(values, dtype=np.float32)
    rows, cols = shape
    row_i, col_i = np.indices((rows, cols))
    full_col = col_i * dest_scale
    full_row = row_i * dest_scale
    lon = dest.origin_lon + dest.col_lon * full_col + dest.row_lon * full_row
    lat = dest.origin_lat + dest.col_lat * full_col + dest.row_lat * full_row
    det = source.col_lon * source.row_lat - source.row_lon * source.col_lat
    if det == 0:
        raise RuntimeError("The source grid has no inverse")
    dlon = lon - source.origin_lon
    dlat = lat - source.origin_lat
    src_col = (source.row_lat * dlon - source.row_lon * dlat) / det / source_scale
    src_row = (-source.col_lat * dlon + source.col_lon * dlat) / det / source_scale
    return map_coordinates(
        grid, [src_row, src_col], order=1, mode="constant", cval=np.nan
    )
