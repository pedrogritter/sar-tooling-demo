"""Measure the Lisbon GRD and dwell stack, then brief only from those numbers.

The GRD supplies the water split, the bright returns, and the bridge
return. The 15-band VID stack supplies what moved during the dwell.
The colorized sub-aperture image is a second vote at those same points.
The SLC is one complex pass: its sidecar is recorded, and the raster is
not turned into a detection.

``OPENAI_API_KEY`` is optional. When it is set, the model writes the
prose from the measurement JSON and nothing else. When it is not set,
the prose is rendered from that same JSON.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image, ImageDraw
from scipy import ndimage

from lisbon_scene.grid import Grid, metres

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "intelligence"
# A return smaller than this is speckle on a 1 m measurement grid.
MIN_RETURN_M2 = 20.0
BRIDGE_MIN_M = 400.0
MOVER_MIN_M = 8.0
DECK_BUFFER_M = 40.0
CALIBRATION = 1.3405353724476985e-05
OnStep = Callable[[int, str], None]
STEP_SENTENCES = (
    "Checking that the GRD is on disk.",
    "Checking that the dwell stack is on disk.",
    "Checking the sub-aperture image.",
    "Measuring dark water and the deck return.",
    "Tracking bright returns across the dwell.",
    "Comparing each return with its sub-aperture neighborhood.",
    "Recording the SLC sidecar without detecting on it.",
    "Drawing the overview.",
    "Writing the measurement, the GeoJSON, and the briefing.",
)


def main() -> None:
    run_measurement()


def run_measurement(on_step: OnStep | None = None) -> None:
    if on_step is None:
        on_step = _print_step

    on_step(1, STEP_SENTENCES[0])
    _require_local_raster("grd-cog.tif")
    on_step(2, STEP_SENTENCES[1])
    _require_local_raster("vid-cog.tif")
    on_step(3, STEP_SENTENCES[2])
    csi_ready = (DATA / "csi-cog.tif").is_file()
    OUT.mkdir(parents=True, exist_ok=True)

    on_step(4, STEP_SENTENCES[3])
    grd_meta = json.loads((DATA / "grd-json.json").read_text(encoding="utf-8"))
    grd = load_reduced(DATA / "grd-cog.tif")
    scene = measure_grd(
        grd, Grid.from_transform(grd_meta["properties"]["proj:transform"])
    )
    on_step(5, STEP_SENTENCES[4])
    vid_meta = json.loads((DATA / "vid-json.json").read_text(encoding="utf-8"))
    stac = json.loads((DATA / "stac.json").read_text(encoding="utf-8"))
    vid, vid_scale = load_video(DATA / "vid-cog.tif")
    vid_grid = Grid.from_transform(vid_meta["properties"]["proj:transform"])
    measure_motion(scene, vid, vid_grid, vid_scale, stac["properties"])
    on_step(6, STEP_SENTENCES[5])
    if csi_ready:
        measure_subaperture(scene, load_reduced(DATA / "csi-cog.tif"))
    on_step(7, STEP_SENTENCES[6])
    scene["slc"] = slc_note()
    on_step(8, STEP_SENTENCES[7])
    save_overview(
        scene["_mean"],
        scene["_water"],
        scene["_bridge"],
        scene["_returns"],
        scene["_grid"],
        scene["_scale"],
    )
    on_step(9, STEP_SENTENCES[8])
    write_products(scene)
    briefing = model_briefing(scene) or render_briefing(scene)
    (OUT / "briefing.md").write_text(briefing, encoding="utf-8")
    print(f"wrote {OUT}")


def _print_step(index: int, sentence: str) -> None:
    print(f"{index}. {sentence}")


def _require_local_raster(raster_name: str) -> None:
    raster = DATA / raster_name
    if not raster.is_file():
        raise RuntimeError(
            f"Missing data/{raster_name}. Run python3 scene.py --all."
        )


def wait_for(raster_name: str, required: bool = True) -> bool:
    """Block until a downloading COG matches its remote size."""

    raster = DATA / raster_name
    key = raster_name.split(".")[0]
    stac = json.loads((DATA / "stac.json").read_text(encoding="utf-8"))
    expected = remote_size(stac["assets"][key]["href"])
    deadline = time.time() + (6 * 60 * 60 if required else 0)
    while True:
        size = raster.stat().st_size if raster.exists() else 0
        if size == expected and expected > 0:
            print(f"ready {raster_name}")
            return True
        if not required or time.time() > deadline:
            print(f"missing {raster_name} ({size} of {expected})")
            return False
        print(f"waiting {raster_name} {size / 1e6:.0f}/{expected / 1e6:.0f} MB")
        time.sleep(10)


def remote_size(href: str) -> int:
    request = urllib.request.Request(href, method="HEAD")
    with urllib.request.urlopen(request, timeout=60) as response:
        return int(response.headers.get("Content-Length") or 0)


def load_reduced(path: Path) -> dict[str, object]:
    """Load a coarse grid from the COG overview nearest a 1 m pixel."""

    with tifffile.TiffFile(path) as tiff:
        series = tiff.series[0]
        full = series.levels[0]
        chosen = full
        for level in series.levels:
            side = max(int(level.shape[0]), int(level.shape[1]))
            if side <= 5000:
                chosen = level
                break
        array = np.asarray(chosen.asarray())
        full_shape = (int(full.shape[0]), int(full.shape[1]))
    bands = None
    if array.ndim == 3 and array.shape[-1] in {3, 4}:
        bands = np.moveaxis(array, -1, 0)
        array = bands.mean(axis=0)
    elif array.ndim == 3 and array.shape[0] in {3, 4}:
        bands = array
        array = array.mean(axis=0)
    overview_scale = full_shape[0] / array.shape[0]
    other = full_shape[1] / array.shape[1]
    if abs(overview_scale - other) > 0.05:
        raise RuntimeError(f"{path.name} overview axes do not share a scale")
    factor = max(1, math.ceil(max(array.shape) / 5000))
    reduced_max = block(array, factor, "max")
    reduced_mean = block(array, factor, "mean")
    band_grid = None
    if bands is not None:
        band_grid = np.stack(
            [block(bands[i], factor, "mean") for i in range(bands.shape[0])]
        )
    return {
        "max": reduced_max,
        "mean": reduced_mean,
        "bands": band_grid,
        "scale": float(overview_scale * factor),
        "full_shape": [full_shape[0], full_shape[1]],
    }


def block(array: np.ndarray, factor: int, how: str) -> np.ndarray:
    rows = array.shape[0] // factor
    cols = array.shape[1] // factor
    view = array[: rows * factor, : cols * factor].reshape(rows, factor, cols, factor)
    if how == "max":
        return view.max(axis=(1, 3))
    return view.mean(axis=(1, 3))


def measure_grd(grd: dict[str, object], grid: Grid) -> dict[str, object]:
    """Split the two dark basins from the city and measure the deck return."""

    mean = np.asarray(grd["mean"])
    maximum = np.asarray(grd["max"])
    scale = float(grd["scale"])
    col_m = metres(*grid.to_lonlat(0, 0, scale), *grid.to_lonlat(1, 0, scale))
    row_m = metres(*grid.to_lonlat(0, 0, scale), *grid.to_lonlat(0, 1, scale))
    pixel_m = min(col_m, row_m)
    pixel_area = col_m * row_m
    mode, speckle_std = dark_peak(mean)
    # 1.35 times the dark mode reaches the brighter basin without the city.
    # 1.6 times the speckle std of that peak rejects textured ground.
    smooth = ndimage.uniform_filter(mean.astype(np.float32), size=15)
    local_std = local_deviation(mean, smooth)
    dark = (smooth <= mode * 1.35) & (local_std <= speckle_std * 1.6)
    water = large_components(dark, 0.01)
    water = ndimage.binary_fill_holes(water)
    bridge = find_bridge(maximum, water, mode, pixel_m, col_m, row_m, grid, scale)
    returns = find_returns(
        maximum, water, bridge, mode, pixel_m, col_m, row_m, grid, scale
    )
    labels, _count = ndimage.label(water)
    basins = basin_records(mean, labels, pixel_area)
    water_km2 = float(water.sum()) * pixel_area / 1e6
    scene_km2 = float(water.size) * pixel_area / 1e6
    water_median = float(np.median(mean[water])) if water.any() else mode
    return {
        "scene_id": "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF",
        "measurement_grid_m": round(pixel_m, 3),
        "water_mode_dn": round(mode, 2),
        "water_threshold_dn": round(mode * 1.35, 2),
        "bright_threshold_dn": round(mode * 6.0, 1),
        "water_km2": round(water_km2, 2),
        "scene_km2": round(scene_km2, 2),
        "water_fraction": round(water_km2 / scene_km2, 3) if scene_km2 else 0.0,
        "water_sigma0_db": round(sigma0_db(water_median), 2),
        "basins": basins,
        "bridge": public_record(bridge) if bridge else None,
        "returns": [public_record(item) for item in returns],
        "_bridge": bridge,
        "_returns": returns,
        "_grid": grid,
        "_scale": scale,
        "_mean": mean,
        "_water": water,
    }


def dark_peak(mean: np.ndarray) -> tuple[float, float]:
    """Mode of the dark peak, and the local std of pixels sitting on that mode."""

    smooth = ndimage.uniform_filter(mean.astype(np.float32), size=15)
    hi = float(np.percentile(smooth, 99))
    hist, edges = np.histogram(smooth, bins=200, range=(float(smooth.min()), hi))
    peak = int(np.argmax(hist))
    mode = float((edges[peak] + edges[peak + 1]) / 2)
    local_std = local_deviation(mean, smooth)
    on_peak = np.abs(smooth - mode) <= max(mode * 0.1, 2)
    speckle = float(np.median(local_std[on_peak])) if on_peak.any() else 1.0
    return mode, speckle


def local_deviation(mean: np.ndarray, smooth: np.ndarray) -> np.ndarray:
    square = ndimage.uniform_filter(mean.astype(np.float32) ** 2, size=15)
    return np.sqrt(np.maximum(square - smooth**2, 0))


def large_components(mask: np.ndarray, minimum_fraction: float) -> np.ndarray:
    """Keep connected pieces larger than a fraction of the frame."""

    labels, count = ndimage.label(mask)
    if count == 0:
        return np.zeros(mask.shape, dtype=bool)
    counts = np.bincount(labels.ravel())
    keep = counts >= minimum_fraction * mask.size
    keep[0] = False
    return keep[labels]


def basin_records(
    mean: np.ndarray, labels: np.ndarray, pixel_area: float
) -> list[dict[str, float]]:
    counts = np.bincount(labels.ravel())
    order = np.argsort(counts)[::-1]
    records: list[dict[str, float]] = []
    for index in order:
        if index == 0 or counts[index] < 0.01 * labels.size:
            continue
        values = mean[labels == index]
        records.append(
            {
                "area_km2": round(float(counts[index]) * pixel_area / 1e6, 2),
                "median_sigma0_db": round(sigma0_db(float(np.median(values))), 2),
            }
        )
    records.sort(key=lambda item: item["area_km2"], reverse=True)
    return records


def find_bridge(
    maximum: np.ndarray,
    water: np.ndarray,
    mode: float,
    pixel_m: float,
    col_m: float,
    row_m: float,
    grid: Grid,
    scale: float,
) -> dict[str, object] | None:
    """Longest bright return in the 120 m band beside the basins."""

    band_px = max(3, int(120 / pixel_m))
    close_px = max(2, int(6 / pixel_m))
    distance = ndimage.distance_transform_edt(~water)
    band = (distance > 0) & (distance <= band_px) & (maximum >= mode * 4)
    band = ndimage.binary_closing(band, iterations=close_px)
    labels, count = ndimage.label(band)
    if count == 0:
        return None
    counts = np.bincount(labels.ravel())
    index = int(np.argmax(counts[1:]) + 1)
    ys, xs = np.nonzero(labels == index)
    if len(xs) < 80:
        return None
    length_m, width_m, axis, centre_col, centre_row = shape_of(xs, ys, col_m, row_m)
    if length_m < BRIDGE_MIN_M:
        return None
    values = maximum[ys, xs]
    lon, lat = grid.to_lonlat(centre_col, centre_row, scale)
    return {
        "kind": "bridge deck return",
        "area_m2": round(float(len(xs)) * col_m * row_m, 1),
        "length_m": round(length_m, 1),
        "width_m": round(width_m, 1),
        "peak_dn": int(values.max()),
        "peak_sigma0_db": round(sigma0_db(float(values.max())), 2),
        "lon": lon,
        "lat": lat,
        "row": centre_row,
        "col": centre_col,
        "axis": axis,
        "mask_rows": ys,
        "mask_cols": xs,
    }


def find_returns(
    maximum: np.ndarray,
    water: np.ndarray,
    bridge: dict[str, object] | None,
    mode: float,
    pixel_m: float,
    col_m: float,
    row_m: float,
    grid: Grid,
    scale: float,
) -> list[dict[str, object]]:
    """Bright pixels beside the water, grouped when they sit within 70 m."""

    distance = ndimage.distance_transform_edt(~water)
    excluded = np.zeros(water.shape, dtype=bool)
    if bridge is not None:
        excluded[bridge["mask_rows"], bridge["mask_cols"]] = True
        grow = max(2, int(8 / pixel_m))
        excluded = ndimage.binary_dilation(excluded, iterations=grow)
    bright = (maximum >= mode * 6) & (distance <= 80 / pixel_m) & ~excluded
    labels, _count = ndimage.label(bright)
    returns: list[dict[str, object]] = []
    for index, window in enumerate(ndimage.find_objects(labels), start=1):
        if window is None:
            continue
        mask = labels[window] == index
        area_m2 = float(mask.sum()) * col_m * row_m
        if area_m2 < MIN_RETURN_M2:
            continue
        rows, cols = np.nonzero(mask)
        centre_row = float(rows.mean() + window[0].start)
        centre_col = float(cols.mean() + window[1].start)
        touch = ring_fraction(
            water, int(centre_row), int(centre_col), int(50 / pixel_m)
        )
        if touch < 0.45:
            continue
        values = maximum[window][mask]
        length_m, width_m, axis = ellipse(cols, rows, col_m, row_m)
        lon, lat = grid.to_lonlat(centre_col, centre_row, scale)
        returns.append(
            {
                "kind": "bright return at the waterline",
                "area_m2": round(area_m2, 1),
                "length_m": round(length_m, 1),
                "width_m": round(width_m, 1),
                "peak_dn": int(values.max()),
                "peak_sigma0_db": round(sigma0_db(float(values.max())), 2),
                "lon": lon,
                "lat": lat,
                "row": centre_row,
                "col": centre_col,
                "axis": axis,
                "water_touch": round(touch, 3),
                "on_water": touch >= 0.5,
            }
        )
    return cluster_returns(returns, 70.0)


def ring_fraction(water: np.ndarray, row: int, col: int, radius: int) -> float:
    """Share of a ring around a point that the basin mask calls water."""

    if radius < 4:
        return 0.0
    height, width = water.shape
    r0, r1 = max(0, row - radius), min(height, row + radius + 1)
    c0, c1 = max(0, col - radius), min(width, col + radius + 1)
    patch = water[r0:r1, c0:c1]
    yy, xx = np.ogrid[r0 - row : r1 - row, c0 - col : c1 - col]
    ring = (yy**2 + xx**2 >= (radius * 0.35) ** 2) & (yy**2 + xx**2 <= radius**2)
    if not ring.any():
        return 0.0
    return float(patch[ring].mean())


def cluster_returns(
    returns: list[dict[str, object]], limit_m: float
) -> list[dict[str, object]]:
    """Fold bright pixels on the same quay or hull into one row."""

    ordered = sorted(
        returns, key=lambda item: float(item["peak_sigma0_db"]), reverse=True
    )
    groups: list[dict[str, object]] = []
    for item in ordered:
        host = None
        for group in groups:
            gap = metres(
                float(group["lon"]),
                float(group["lat"]),
                float(item["lon"]),
                float(item["lat"]),
            )
            if gap <= limit_m:
                host = group
                break
        if host is None:
            groups.append(dict(item))
            continue
        host["area_m2"] = round(float(host["area_m2"]) + float(item["area_m2"]), 1)
        if float(item["peak_sigma0_db"]) > float(host["peak_sigma0_db"]):
            host["peak_sigma0_db"] = item["peak_sigma0_db"]
            host["peak_dn"] = item["peak_dn"]
            host["lon"] = item["lon"]
            host["lat"] = item["lat"]
            host["row"] = item["row"]
            host["col"] = item["col"]
    groups.sort(key=lambda item: float(item["area_m2"]), reverse=True)
    return groups


def shape_of(
    cols: np.ndarray, rows: np.ndarray, col_m: float, row_m: float
) -> tuple[float, float, tuple[float, float], float, float]:
    """End-to-end length, robust width, unit axis in pixels, and the centre."""

    coords = np.column_stack(
        [cols.astype(float) * col_m, rows.astype(float) * row_m]
    )
    centre = coords.mean(axis=0)
    spread = coords - centre
    cov = np.cov(spread, rowvar=False)
    values, vectors = np.linalg.eigh(cov)
    order = int(np.argmax(values))
    axis_m = vectors[:, order]
    proj = spread @ axis_m
    length = float(proj.max() - proj.min())
    perp = spread @ np.array([-axis_m[1], axis_m[0]])
    width = float(np.percentile(perp, 95) - np.percentile(perp, 5))
    axis_col = float(axis_m[0]) / col_m
    axis_row = float(axis_m[1]) / row_m
    norm = math.hypot(axis_col, axis_row) or 1.0
    centre_col = float(centre[0] / col_m)
    centre_row = float(centre[1] / row_m)
    return length, width, (axis_col / norm, axis_row / norm), centre_col, centre_row


def ellipse(
    cols: np.ndarray, rows: np.ndarray, col_m: float, row_m: float
) -> tuple[float, float, tuple[float, float]]:
    """Length and width in metres, plus a unit axis in coarse pixels."""

    coords = np.column_stack(
        [cols.astype(float) * col_m, rows.astype(float) * row_m]
    )
    centre = coords.mean(axis=0)
    spread = coords - centre
    if len(coords) < 3:
        return col_m, row_m, (1.0, 0.0)
    cov = np.cov(spread, rowvar=False)
    values, vectors = np.linalg.eigh(cov)
    order = int(np.argmax(values))
    length = 4 * math.sqrt(max(float(values[order]), 0.0))
    width = 4 * math.sqrt(max(float(values[1 - order]), 0.0))
    axis_col = float(vectors[0, order]) / col_m
    axis_row = float(vectors[1, order]) / row_m
    norm = math.hypot(axis_col, axis_row) or 1.0
    return length, width, (axis_col / norm, axis_row / norm)


def near_bridge(
    item: dict[str, object], bridge: dict[str, object] | None, grid: Grid, scale: float
) -> bool:
    if bridge is None:
        return False
    return point_line_m(item, bridge, grid, scale) <= DECK_BUFFER_M


def point_line_m(
    item: dict[str, object], bridge: dict[str, object], grid: Grid, scale: float
) -> float:
    ends = bridge_ends(bridge, grid, scale)
    return segment_distance_m(
        (float(item["lon"]), float(item["lat"])), ends[0], ends[1]
    )


def bridge_ends(
    bridge: dict[str, object], grid: Grid, scale: float
) -> tuple[tuple[float, float], tuple[float, float]]:
    half = float(bridge["length_m"]) / 2
    axis_col, axis_row = bridge["axis"]  # type: ignore[misc]
    centre_col = float(bridge["col"])
    centre_row = float(bridge["row"])
    col_m = metres(*grid.to_lonlat(0, 0, scale), *grid.to_lonlat(1, 0, scale))
    row_m = metres(*grid.to_lonlat(0, 0, scale), *grid.to_lonlat(0, 1, scale))
    step = math.hypot(axis_col * col_m, axis_row * row_m)
    span = half / step
    start = grid.to_lonlat(
        centre_col - axis_col * span, centre_row - axis_row * span, scale
    )
    end = grid.to_lonlat(
        centre_col + axis_col * span, centre_row + axis_row * span, scale
    )
    return start, end


def segment_distance_m(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Distance from a lon/lat point to a short segment, in metres."""

    # Work in a local metre frame around the point so the segment test is linear.
    def frame(lon: float, lat: float) -> tuple[float, float]:
        east = (lon - point[0]) * 111_320 * math.cos(math.radians(point[1]))
        north = (lat - point[1]) * 110_540
        return east, north

    ax, ay = frame(*start)
    bx, by = frame(*end)
    abx, aby = bx - ax, by - ay
    denom = abx * abx + aby * aby
    if denom == 0:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, (-ax * abx - ay * aby) / denom))
    return math.hypot(ax + abx * t, ay + aby * t)


def measure_motion(
    scene: dict[str, object],
    vid: np.ndarray,
    grid: Grid,
    vid_scale: float,
    properties: dict[str, object],
) -> None:
    """Track each return across the dwell frames and count change on the deck line."""

    frames = int(vid.shape[0])
    start = parse_time(str(properties["start_datetime"]))
    end = parse_time(str(properties["end_datetime"]))
    dwell_s = (end - start).total_seconds()
    step_s = dwell_s / max(frames - 1, 1)
    pixel_m = metres(
        *grid.to_lonlat(0, 0, vid_scale), *grid.to_lonlat(1, 0, vid_scale)
    )
    row_m = metres(
        *grid.to_lonlat(0, 0, vid_scale), *grid.to_lonlat(0, 1, vid_scale)
    )
    # Two pixels of the coarser axis. One-pixel speckle wander is not motion.
    mover_min = max(MOVER_MIN_M, 2 * max(pixel_m, row_m))
    radius = max(2, int(15 / pixel_m))
    for item in scene["_returns"]:  # type: ignore[index]
        col, row = grid.to_colrow(float(item["lon"]), float(item["lat"]), vid_scale)
        track = track_peak(vid, row, col, radius)
        item["track_frames"] = len(track)
        if len(track) < 2:
            item["displacement_m"] = 0.0
            item["speed_m_s"] = 0.0
            item["motion"] = "not tracked"
            continue
        first, last = track[0], track[-1]
        shift = metres(
            *grid.to_lonlat(first[1], first[0], vid_scale),
            *grid.to_lonlat(last[1], last[0], vid_scale),
        )
        elapsed = (last[2] - first[2]) * step_s
        item["displacement_m"] = round(shift, 1)
        item["speed_m_s"] = round(shift / elapsed, 2) if elapsed else 0.0
        item["motion"] = (
            "moved" if shift >= mover_min else "stationary during the dwell"
        )
        if near_bridge(item, scene["_bridge"], scene["_grid"], scene["_scale"]):  # type: ignore[arg-type]
            item["kind"] = "bright return on the deck line"
    bridge = scene["_bridge"]
    changes = 0
    if isinstance(bridge, dict):
        changes = deck_changes(
            vid,
            grid,
            vid_scale,
            bridge,
            scene["_grid"],
            scene["_scale"],
            pixel_m,
        )  # type: ignore[arg-type]
    scene["dwell_s"] = round(dwell_s, 3)
    scene["dwell_frames"] = frames
    scene["deck_changes"] = changes
    scene["deck_changes_note"] = (
        "Clusters of high frame-to-frame variance within 40 m of the deck line. "
        "Not a vehicle count."
    )
    for item in scene["returns"]:  # type: ignore[index]
        match = next(raw for raw in scene["_returns"] if raw["lon"] == item["lon"])  # type: ignore[index]
        item["motion"] = match.get("motion", "not tracked")
        item["displacement_m"] = match.get("displacement_m", 0.0)
        item["speed_m_s"] = match.get("speed_m_s", 0.0)
        item["kind"] = match["kind"]


def track_peak(
    vid: np.ndarray,
    row: float,
    col: float,
    radius: int,
) -> list[tuple[float, float, int]]:
    """Follow one bright peak. Each frame searches around the previous hit."""

    frames, height, width = vid.shape
    track: list[tuple[float, float, int]] = []
    current_row, current_col = row, col
    floor = 0.0
    for index in range(frames):
        r0 = max(0, int(current_row) - radius)
        r1 = min(height, int(current_row) + radius + 1)
        c0 = max(0, int(current_col) - radius)
        c1 = min(width, int(current_col) + radius + 1)
        window = vid[index, r0:r1, c0:c1]
        if window.size == 0:
            continue
        peak_dn = float(window.max())
        if index == 0:
            floor = peak_dn * 0.5
        if peak_dn < floor:
            continue
        peak = np.unravel_index(int(np.argmax(window)), window.shape)
        current_row = r0 + float(peak[0])
        current_col = c0 + float(peak[1])
        track.append((current_row, current_col, index))
    return track


def deck_changes(
    vid: np.ndarray,
    vid_grid: Grid,
    vid_scale: float,
    bridge: dict[str, object],
    grd_grid: Grid,
    scale: float,
    pixel_m: float,
) -> int:
    start, end = bridge_ends(bridge, grd_grid, scale)
    mask = np.zeros(vid.shape[1:], dtype=bool)
    c0, r0 = vid_grid.to_colrow(*start, vid_scale)
    c1, r1 = vid_grid.to_colrow(*end, vid_scale)
    draw_segment(mask, c0, r0, c1, r1)
    distance = ndimage.distance_transform_edt(~mask)
    near = distance <= (DECK_BUFFER_M / pixel_m)
    deviation = vid.std(axis=0)
    level = float(np.percentile(deviation[near], 99.5)) if near.any() else 0.0
    active = (deviation >= level) & near
    labels, _count = ndimage.label(active)
    minimum = MIN_RETURN_M2 / max(pixel_m * pixel_m, 1e-6)
    kept = 0
    for index, window in enumerate(ndimage.find_objects(labels), start=1):
        if window is None:
            continue
        if int((labels[window] == index).sum()) >= minimum:
            kept += 1
    return kept


def draw_segment(mask: np.ndarray, c0: float, r0: float, c1: float, r1: float) -> None:
    steps = int(max(abs(c1 - c0), abs(r1 - r0))) + 1
    cols = np.linspace(c0, c1, steps)
    rows = np.linspace(r0, r1, steps)
    height, width = mask.shape
    col_i = np.clip(np.rint(cols).astype(int), 0, width - 1)
    row_i = np.clip(np.rint(rows).astype(int), 0, height - 1)
    mask[row_i, col_i] = True


def measure_subaperture(scene: dict[str, object], csi: dict[str, object]) -> None:
    """Flag a return whose sub-aperture mix disagrees with its neighborhood."""

    bands = csi["bands"]
    if not isinstance(bands, np.ndarray):
        scene["subaperture"] = "CSI has no separate bands on the grid that was read"
        return
    scale = float(csi["scale"])
    grd_scale = float(scene["_scale"])
    for item in scene["_returns"]:  # type: ignore[index]
        row = int(float(item["row"]) * grd_scale / scale)
        col = int(float(item["col"]) * grd_scale / scale)
        if not (0 <= row < bands.shape[1] and 0 <= col < bands.shape[2]):
            continue
        local = bands[:, max(0, row - 5) : row + 6, max(0, col - 5) : col + 6]
        centre = bands[:, row, col].astype(float)
        neighbor = local.mean(axis=(1, 2))
        item["subaperture_outlier"] = mix(centre) > mix(neighbor) + 0.15
    for published, raw in zip(scene["returns"], scene["_returns"], strict=True):  # type: ignore[arg-type]
        if "subaperture_outlier" in raw:
            published["subaperture_outlier"] = raw["subaperture_outlier"]


def mix(values: np.ndarray) -> float:
    total = float(values.sum())
    if total <= 0:
        return 0.0
    share = values / total
    return float(share.max() - share.min())


def load_video(path: Path) -> tuple[np.ndarray, float]:
    """Load the dwell overview. Returns frames-first array and full-pixel scale."""

    with tifffile.TiffFile(path) as tiff:
        series = tiff.series[0]
        full = series.levels[0]
        chosen = full
        for level in series.levels:
            side = max(int(level.shape[0]), int(level.shape[1]))
            if side <= 4000:
                chosen = level
                break
        array = np.asarray(chosen.asarray())
        full_h = int(full.shape[0])
        full_w = int(full.shape[1])
    if array.ndim != 3:
        raise RuntimeError(f"VID stack shape {array.shape} is not a frame cube")
    if array.shape[-1] <= 16:
        array = np.moveaxis(array, -1, 0)
    scale = full_h / array.shape[1]
    other = full_w / array.shape[2]
    if abs(scale - other) > 0.05:
        raise RuntimeError(f"{path.name} overview axes do not share a scale")
    return array, float(scale)


def slc_note() -> dict[str, object]:
    meta = json.loads((DATA / "slc-json.json").read_text(encoding="utf-8"))
    props = meta["properties"]
    path = DATA / "slc-cog.tif"
    size = path.stat().st_size if path.exists() else 0
    return {
        "product": "SLC-COG",
        "shape": props["proj:shape"],
        "bands": "two float32 planes, the complex sample",
        "range_resolution_m": props["sar:resolution_range"],
        "azimuth_resolution_m": props["sar:resolution_azimuth"],
        "bytes_on_disk": size,
        "used_for_detection": False,
        "reason": (
            "One SLC has no second pass to interfere, "
            "and the dwell stack already carries the motion."
        ),
    }


def public_record(item: dict[str, object] | None) -> dict[str, object] | None:
    if item is None:
        return None
    keep = (
        "kind",
        "area_m2",
        "length_m",
        "width_m",
        "peak_dn",
        "peak_sigma0_db",
        "lon",
        "lat",
        "on_water",
        "water_touch",
        "motion",
        "displacement_m",
        "speed_m_s",
        "subaperture_outlier",
    )
    return {key: item[key] for key in keep if key in item}


def save_overview(
    mean: np.ndarray,
    water: np.ndarray,
    bridge: dict[str, object] | None,
    returns: list[dict[str, object]],
    grid: Grid,
    scale: float,
) -> None:
    low, high = np.percentile(mean, [2, 98])
    gray = np.clip((mean - low) / max(high - low, 1), 0, 1)
    image = Image.fromarray((gray * 255).astype(np.uint8)).convert("RGB")
    draw = ImageDraw.Draw(image)
    # Tint water pixels lightly so the split is visible without hiding the radar.
    tint = np.array(image)
    tint[water, 2] = np.minimum(255, tint[water, 2].astype(int) + 40)
    image = Image.fromarray(tint)
    draw = ImageDraw.Draw(image)
    if bridge is not None:
        start, end = bridge_ends(bridge, grid, scale)
        draw.line(
            [to_pixel(grid, start, scale), to_pixel(grid, end, scale)],
            fill=(255, 170, 30),
            width=5,
        )
    for item in returns:
        col, row = grid.to_colrow(float(item["lon"]), float(item["lat"]), scale)
        box = [col - 18, row - 18, col + 18, row + 18]
        moved = item.get("motion") == "moved"
        draw.rectangle(box, outline=(255, 60, 40) if moved else (70, 220, 255))
    image.save(OUT / "overview.png")


def to_pixel(
    grid: Grid, lonlat: tuple[float, float], scale: float
) -> tuple[float, float]:
    col, row = grid.to_colrow(lonlat[0], lonlat[1], scale)
    return col, row


def write_products(scene: dict[str, object]) -> None:
    public = {key: value for key, value in scene.items() if not key.startswith("_")}
    (OUT / "measurements.json").write_text(
        json.dumps(public, indent=2), encoding="utf-8"
    )
    features: list[dict[str, object]] = []
    bridge = scene.get("bridge")
    if isinstance(bridge, dict):
        start, end = bridge_ends(scene["_bridge"], scene["_grid"], scene["_scale"])  # type: ignore[arg-type]
        features.append(
            {
                "type": "Feature",
                "properties": bridge,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [list(start), list(end)],
                },
            }
        )
    for item in scene["returns"]:  # type: ignore[index]
        features.append(
            {
                "type": "Feature",
                "properties": item,
                "geometry": {
                    "type": "Point",
                    "coordinates": [item["lon"], item["lat"]],
                },
            }
        )
    collection = {"type": "FeatureCollection", "features": features}
    (OUT / "returns.geojson").write_text(
        json.dumps(collection, indent=2), encoding="utf-8"
    )


def sigma0_db(dn: float) -> float:
    """ICEYE GRD amplitude to decibels. sigma0 = calibration_factor * DN^2."""

    linear = CALIBRATION * dn * dn
    if linear <= 0:
        return -99.0
    return 10 * math.log10(linear)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def render_briefing(scene: dict[str, object]) -> str:
    returns = scene["returns"]  # type: ignore[index]
    moved = [item for item in returns if item.get("motion") == "moved"]
    bridge = scene.get("bridge") or {}
    basins = scene.get("basins") or []
    lines = [
        "# Lisbon dwell briefing",
        "",
        "Rendered from `measurements.json`. No model was called.",
        "",
        (
            f"Dark smooth water covers {scene['water_km2']} km² "
            f"of the {scene['scene_km2']} km² frame "
            f"({scene['water_fraction']}). "
            f"Median water sigma0 is {scene['water_sigma0_db']} dB. "
            f"The measurement grid is {scene['measurement_grid_m']} m."
        ),
    ]
    for index, basin in enumerate(basins, start=1):
        lines.append(
            f"Basin {index}: {basin['area_km2']} km², "
            f"median {basin['median_sigma0_db']} dB."
        )
    lines.append("")
    if bridge:
        lines.append(
            f"The deck return runs {bridge['length_m']} m end to end "
            f"and is {bridge['width_m']} m across, "
            f"peak {bridge['peak_sigma0_db']} dB. "
            "The width is the bright radar return, layover included, "
            "not the roadway. It is not a traffic count."
        )
        lines.append("")
    lines.append(
        f"Bright returns at the waterline: {len(returns)}. "
        f"Shifted during the {scene.get('dwell_s')} s dwell: {len(moved)}. "
        "The dwell does not separate vehicles on the deck from the "
        "deck's own speckle, so there is no traffic count."
    )
    lines.append("")
    for item in returns:
        lines.append(
            "- "
            f"{item['lat']:.5f} N, {abs(float(item['lon'])):.5f} W, "
            f"{item.get('motion', 'not tracked')}, "
            f"{item.get('displacement_m', 0)} m, "
            f"{item.get('speed_m_s', 0)} m/s, "
            f"area {item['area_m2']} m², "
            f"peak {item['peak_sigma0_db']} dB"
        )
    lines.append("")
    lines.append(
        "A row is a bright radar return. It is not a named ship. "
        "The SLC is one complex pass and was not used for these detections."
    )
    lines.append("")
    return "\n".join(lines)


def _without_raw_dn(value: object) -> object:
    """Drop raw pixel values so the model cannot report them as decibels."""

    if isinstance(value, dict):
        return {
            key: _without_raw_dn(item)
            for key, item in value.items()
            if key != "peak_dn"
        }
    if isinstance(value, list):
        return [_without_raw_dn(item) for item in value]
    return value


def load_local_env() -> None:
    """Read KEY=value lines from .env. An existing environment value wins."""

    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip().removeprefix("export ").strip()
        value = value.strip().strip("'").strip('"')
        if name and name not in os.environ:
            os.environ[name] = value


def model_briefing(scene: dict[str, object]) -> str | None:
    """Ask the model to phrase the JSON. Refuse the call when no key is set."""

    load_local_env()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print("OPENAI_API_KEY is unset; briefing rendered from the measurements")
        return None
    public = {
        name: _without_raw_dn(value)
        for name, value in scene.items()
        if not name.startswith("_")
    }
    returns = public.get("returns")
    moved = 0
    if isinstance(returns, list):
        moved = sum(1 for item in returns if item.get("motion") == "moved")
    payload = {
        "model": "gpt-4o-mini",
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Write four or five short prose paragraphs. "
                    "Do not return JSON, a code block, "
                    "or a field-by-field restatement. "
                    "Use only numbers that are in the JSON. "
                    "Include the water area, both basin areas and their median sigma0, "
                    "the deck length, deck width, and deck peak_sigma0_db. "
                    "Brightness is peak_sigma0_db, in dB. "
                    "A return is moving only when its motion field "
                    "is exactly \"moved\". "
                    "For each moving return give coordinates, displacement, speed, "
                    "area, and peak_sigma0_db. "
                    "Call a row a bright return or a moving return, never a ship type. "
                    "Do not add objects, counts, or causes that are not in the JSON. "
                    "Say that the deck-line changes are a 15-second sample, "
                    "not a congestion class."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Write the briefing in this order, as prose, "
                    "using only these numbers.\n"
                    "1. Water area, scene area, water fraction, water sigma0, "
                    "then each basin area and its median sigma0.\n"
                    "2. Deck length, width, and peak_sigma0_db. "
                    "Say the deck-line changes are a 15-second sample, "
                    "not a congestion class.\n"
                    f"3. Exactly {moved} moving returns. "
                    "For each one give coordinates, "
                    "displacement_m, speed_m_s, area_m2, and peak_sigma0_db.\n"
                    "Do not add a cause for any number.\n"
                    + json.dumps(public)
                ),
            },
        ],
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.loads(response.read().decode())
    text = str(body["choices"][0]["message"]["content"]).strip()
    if text.startswith("{") or text.startswith("```"):
        print("model returned structured text; keeping the measurement briefing")
        return None
    return (
        "# Lisbon dwell briefing\n\nModel text from `measurements.json` only.\n\n"
        + text
        + "\n"
    )


if __name__ == "__main__":
    main()
