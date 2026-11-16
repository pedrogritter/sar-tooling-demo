"""Stack measurements. Every array is already on the same overview grid."""

from __future__ import annotations

from typing import cast

import numpy as np
from scipy import ndimage

from scene.toolkit.measure import (
    CHANGE_DB,
    CHANGE_SUPPORT,
    change_masks,
    water_mask,
    waterline_returns,
)


def persistence(masks: list[np.ndarray]) -> np.ndarray:
    """Fraction of dates each pixel is water, from 0 to 1."""

    if not masks:
        raise RuntimeError("A stack needs at least one water mask")
    stacked = np.stack([mask.astype(np.float32) for mask in masks], axis=0)
    return stacked.mean(axis=0)


def sea_state(frames: list[np.ndarray], masks: list[np.ndarray]) -> list[float | None]:
    """Median water sigma-nought for each date. None when that date has no water."""

    levels: list[float | None] = []
    for frame, mask in zip(frames, masks, strict=True):
        values = frame[mask & np.isfinite(frame)]
        if values.size == 0:
            levels.append(None)
            continue
        levels.append(round(float(np.median(values)), 2))
    return levels


def dark_anomaly(
    frame: np.ndarray,
    median: np.ndarray,
    water: np.ndarray,
    *,
    dark_db: float = 2.0,
    support_px: int = 8,
    ring_db: float = 1.0,
) -> np.ndarray:
    """A dark patch inside water that is darker than the stack median sea.

    The ring around the patch has to be brighter than the patch by
    ``ring_db``, so a sea that is dark everywhere does not become an
    anomaly. The title stays dark sea anomaly.
    """

    sea = np.isfinite(frame) & np.isfinite(median) & water
    candidate = sea & (frame <= median - dark_db)
    labels, count = ndimage.label(candidate)
    keep = np.zeros(frame.shape, dtype=bool)
    for index in range(1, count + 1):
        component = labels == index
        if int(component.sum()) < int(support_px):
            continue
        ring = ndimage.binary_dilation(component, iterations=2) & ~component & sea
        if not ring.any():
            continue
        if float(np.mean(frame[ring])) > float(np.mean(frame[component])) + ring_db:
            keep |= component
    return keep


def shoreline(mask: np.ndarray, *, width_px: int = 1) -> np.ndarray:
    """The water-mask boundary, ``width_px`` pixels wide. One pixel is the default."""

    eroded = ndimage.binary_erosion(mask, iterations=max(int(width_px), 1))
    return cast(np.ndarray, mask & ~eroded)


def date_of_change(
    frames: list[np.ndarray],
    *,
    change_db: float = CHANGE_DB,
    support_px: int = CHANGE_SUPPORT,
) -> tuple[np.ndarray, np.ndarray]:
    """Index of the date furthest from the stack median, and whether it counts.

    A departure under ``change_db`` stays unlabeled, as does a patch under
    ``support_px`` pixels. The index is -1 there. The counted pixels are
    the ones coloured.
    """

    stack = np.stack(frames, axis=0)
    median = np.nanmedian(stack, axis=0)
    distance = np.abs(stack - median)
    distance[~np.isfinite(distance)] = -1
    which = np.argmax(distance, axis=0).astype(np.int16)
    peak = distance.max(axis=0)
    # Same support rule as amplitude change, so one speckled pixel is unlabeled.
    keep = change_masks(
        median,
        median + np.where(peak >= change_db, peak, 0),
        change_db=change_db,
        support_px=support_px,
    )[1]
    which = np.where(keep, which, -1)
    return which, keep


def site_activity(
    frame: np.ndarray,
    median: np.ndarray,
    mode_db: float,
    *,
    bright_offset_db: float = 8.0,
    min_pixels: int = 4,
) -> tuple[np.ndarray, np.ndarray]:
    """Bright clusters that are new on this date, and clusters the median had."""

    present = np.isfinite(frame) & (frame >= mode_db + bright_offset_db)
    usual = np.isfinite(median) & (median >= mode_db + bright_offset_db)
    count = int(min_pixels)
    appeared = _large_components(present & ~usual, count)
    left = _large_components(usual & ~present, count)
    return appeared, left


def repeat_counts(
    frames: list[np.ndarray],
    masks: list[np.ndarray],
    modes: list[float],
    col_m: float,
    row_m: float,
    *,
    match_m: float = 80.0,
) -> list[tuple[float, float, int]]:
    """Centres of waterline returns and how many dates they appear on.

    ``match_m`` is how far apart two hits can sit and still be one return.
    Six overview pixels remain the floor under that distance.
    """

    groups: list[list[tuple[float, float]]] = []
    limit = max(match_m, min(col_m, row_m) * 6)
    for frame, mask, mode in zip(frames, masks, modes, strict=True):
        for component in waterline_returns(frame, mask, mode, col_m, row_m):
            placed = False
            for group in groups:
                row, col = group[0]
                gap = (
                    (component.row - row) ** 2 * row_m**2
                    + (component.col - col) ** 2 * col_m**2
                ) ** 0.5
                if gap <= limit:
                    group.append((component.row, component.col))
                    placed = True
                    break
            if not placed:
                groups.append([(component.row, component.col)])
    counts: list[tuple[float, float, int]] = []
    for group in groups:
        row = float(np.mean([item[0] for item in group]))
        col = float(np.mean([item[1] for item in group]))
        counts.append((row, col, len(group)))
    return counts


def stack_median(frames: list[np.ndarray]) -> np.ndarray:
    return cast(np.ndarray, np.nanmedian(np.stack(frames, axis=0), axis=0)).astype(
        np.float32
    )


def stack_mean(frames: list[np.ndarray]) -> np.ndarray:
    return np.nanmean(np.stack(frames, axis=0), axis=0).astype(np.float32)


def frame_mode(frame: np.ndarray) -> float:
    _mask, mode = water_mask(frame)
    return mode


def _large_components(mask: np.ndarray, minimum: int) -> np.ndarray:
    labels, count = ndimage.label(mask)
    if count == 0:
        return np.zeros(mask.shape, dtype=bool)
    counts = np.bincount(labels.ravel())
    keep = counts >= minimum
    keep[0] = False
    return cast(np.ndarray, keep[labels])
