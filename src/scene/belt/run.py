"""Run one belt tool and write its picture, measurement, and briefing."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PIL import Image

from scene.grid import Grid
from scene.paths import scene_dir

from .catalog import analysis_dir, tool_spec, tools_for_scene
from .geometry import warp_affine
from .measure import (
    built_up_mask,
    change_masks,
    long_structure,
    split_roughness,
    track_returns,
    water_mask,
    waterline_returns,
)
from .picture import MaskLayer, Stroke, attach_bars, render, with_legend
from .raster import (
    calibration_factor,
    dwell_seconds,
    load_amplitude,
    load_video,
    percentile_range,
    pixel_metres,
    read_json,
    sigma0_db,
    stretch,
)
from .stack import (
    dark_anomaly,
    date_of_change,
    frame_mode,
    persistence,
    repeat_counts,
    sea_state,
    shoreline,
    site_activity,
    stack_mean,
    stack_median,
)

OnStep = Callable[[int, str], None]
Color = tuple[int, int, int]
WATER: Color = (40, 110, 210)
CALM: Color = (20, 70, 170)
ROUGH: Color = (140, 190, 210)
BUILT: Color = (210, 120, 50)
MARK: Color = (70, 220, 255)
MOVED: Color = (255, 80, 60)
STRUCTURE: Color = (255, 190, 40)
ANOMALY: Color = (250, 210, 40)
NEW: Color = (80, 220, 230)
GONE: Color = (230, 70, 70)
DATE_COLORS: tuple[Color, ...] = (
    (66, 135, 245),
    (235, 87, 87),
    (39, 174, 96),
    (242, 153, 74),
    (155, 81, 224),
    (86, 204, 242),
    (242, 201, 76),
    (235, 87, 168),
)
LIMITS = {
    "open-water": (
        "Shadow, tarmac, and sand are dark for the same reason. "
        "Flooded vegetation and flooded streets get brighter, "
        "so this mask marks them dry."
    ),
    "sea-roughness": (
        "This split is roughness, not a wave period, a wave height, or a current."
    ),
    "built-up": (
        "Brightness is a double-bounce return. It is not a building height "
        "and it is not a residential or industrial class."
    ),
    "returns-on-water": (
        "A row is a bright radar return. A hull, a pier, and a platform all qualify."
    ),
    "long-structure": (
        "The length is the bright return, layover included. "
        "An empty class is a valid result."
    ),
    "dwell-motion": (
        "The stare is the length of this collect. "
        "A track is motion during those seconds, "
        "not a route."
    ),
    "amplitude-change": (
        "Red is the earlier date and has fled. Cyan is the later date and is new. "
        "Gray held its brightness. The areas are the measurement."
    ),
    "water-persistence": "Light blue is rare water. Solid blue is water on every date.",
    "sea-state": (
        "The bars are the median sigma-nought of the water mask. "
        "A low bar is a calm sea."
    ),
    "dark-sea-anomaly": (
        "A film is one cause. The same shape can be a biogenic film, a wind shadow, "
        "rain, or a current boundary. The title is dark sea anomaly."
    ),
    "shoreline-series": (
        "Each colour is one date. The shift is a waterline, not a tide height."
    ),
    "date-of-change": (
        "A pixel is coloured only when it leaves the stack median by 1.5 dB."
    ),
    "repeat-returns": (
        "Many dates is a rock, a pier, or a moored hull. One date is a passing return."
    ),
    "site-activity": (
        "Cyan is a bright cluster new on this date. Red is a bright cluster the stack "
        "median had and this date does not."
    ),
    "stack-mean": "Averaging matched dates cuts speckle where the surface was stable.",
}


@dataclass(frozen=True)
class Frame:
    scene_id: str
    collected_at: str
    db: np.ndarray
    grid: Grid
    scale: float
    col_m: float
    row_m: float
    low: float
    high: float


def step_sentences(tool_id: str) -> tuple[str, ...]:
    if tool_id == "dwell-motion":
        return (
            "Checking that the GRD is on disk.",
            "Checking that the dwell stack is on disk.",
            "Measuring bright returns on the water.",
            "Tracking those returns across the dwell.",
            "Drawing the tracks and the legend.",
            "Writing the measurement and the briefing.",
        )
    if tool_id == "amplitude-change":
        return (
            "Checking both GRDs.",
            "Resampling the second scene onto this grid.",
            "Measuring darker and brighter area.",
            "Drawing the red and cyan composite.",
            "Writing the measurement and the briefing.",
        )
    if tool_id in {
        "water-persistence",
        "sea-state",
        "dark-sea-anomaly",
        "shoreline-series",
        "date-of-change",
        "repeat-returns",
        "site-activity",
        "stack-mean",
    }:
        return (
            "Checking the matched scenes.",
            "Resampling them onto this grid.",
            "Measuring the stack.",
            "Drawing the picture and the legend.",
            "Writing the measurement and the briefing.",
        )
    return (
        "Checking that the GRD is on disk.",
        "Reading the calibration factor.",
        "Measuring the scene.",
        "Drawing the decibel picture and the legend.",
        "Writing the measurement and the briefing.",
    )


def run_tool(
    scene_id: str,
    tool_id: str,
    on_step: OnStep,
    partner_id: str | None = None,
) -> None:
    """Run one tool for ``scene_id``. A locked tool raises with its sentence."""

    spec = tool_spec(tool_id)
    views = {item.id: item for item in tools_for_scene(scene_id)}
    view = views[tool_id]
    if view.locked:
        raise RuntimeError(view.reason)
    if spec.kind == "pair":
        if not partner_id or partner_id not in view.partners:
            raise RuntimeError(
                "Choose a second scene with the same orbit direction and look side."
            )
        _run_change(scene_id, partner_id, on_step)
        return
    if spec.kind in {"stack", "stack-mean"}:
        _run_stack(scene_id, tool_id, view.partners, on_step)
        return
    if tool_id == "dwell-motion":
        _run_motion(scene_id, on_step)
        return
    _run_single(scene_id, tool_id, on_step)


def _run_single(scene_id: str, tool_id: str, on_step: OnStep) -> None:
    sentences = step_sentences(tool_id)
    on_step(1, sentences[0])
    frame = _load_frame(scene_id)
    on_step(2, sentences[1])
    water, mode = water_mask(frame.db)
    on_step(3, sentences[2])
    summary, layers, strokes, legend = _single_layers(tool_id, frame, water, mode)
    on_step(4, sentences[3])
    gray = stretch(frame.db, frame.low, frame.high)
    legend = [
        f"Backdrop is sigma-nought, {frame.low:.0f} to {frame.high:.0f} dB, "
        "2nd to 98th percentile.",
        *legend,
        LIMITS[tool_id],
    ]
    image = render(gray, layers, strokes, legend)
    on_step(5, sentences[4])
    _write(scene_id, tool_id, None, summary, legend, image, LIMITS[tool_id])


def _single_layers(
    tool_id: str,
    frame: Frame,
    water: np.ndarray,
    mode: float,
) -> tuple[
    list[dict[str, str]],
    list[MaskLayer],
    list[Stroke],
    list[str],
]:
    area_m2 = float(water.sum()) * frame.col_m * frame.row_m
    scene_m2 = float(water.size) * frame.col_m * frame.row_m
    if tool_id == "open-water":
        median = _median(frame.db, water)
        summary = [
            {"label": "Water area", "value": f"{area_m2 / 1e6:.2f} km²"},
            {
                "label": "Water fraction",
                "value": f"{(area_m2 / scene_m2) if scene_m2 else 0:.3f}",
            },
            {"label": "Median sigma-nought", "value": _db_text(median)},
        ]
        return (
            summary,
            [MaskLayer(water, WATER)],
            [],
            ["Blue: open water."],
        )
    if tool_id == "sea-roughness":
        calm, rough, note = split_roughness(frame.db, water)
        summary = [
            {"label": "Calm area", "value": _km2(calm, frame)},
            {"label": "Rough area", "value": _km2(rough, frame)},
            {"label": "Calm median", "value": _db_text(_median(frame.db, calm))},
            {"label": "Rough median", "value": _db_text(_median(frame.db, rough))},
        ]
        return (
            summary,
            [MaskLayer(calm, CALM), MaskLayer(rough, ROUGH)],
            [],
            ["Dark blue: calm water.", "Light blue: wind-roughened water.", note],
        )
    if tool_id == "built-up":
        built = built_up_mask(frame.db, water, mode)
        land = max(float((~water).sum()) * frame.col_m * frame.row_m, 1.0)
        built_area = float(built.sum()) * frame.col_m * frame.row_m
        labels, count = _count_parts(built)
        summary = [
            {"label": "Built-up fraction of land", "value": f"{built_area / land:.3f}"},
            {"label": "Clusters", "value": str(count)},
        ]
        del labels
        return summary, [MaskLayer(built, BUILT)], [], ["Warm tint: built-up return."]
    structure = long_structure(frame.db, water, mode, frame.col_m, frame.row_m)
    excluded = structure.mask if structure is not None else None
    if tool_id == "long-structure":
        strokes: list[Stroke] = []
        if structure is None:
            summary = [{"label": "Long structure", "value": "none"}]
            legend = ["No long bright structure on the waterline."]
        else:
            summary = [
                {"label": "Length", "value": f"{structure.length_m:.0f} m"},
                {"label": "Width", "value": f"{structure.width_m:.0f} m"},
                {"label": "Peak sigma-nought", "value": f"{structure.peak_db:.1f} dB"},
            ]
            rows, cols = np.nonzero(structure.mask)
            strokes = [
                Stroke(
                    (
                        (float(cols.min()), float(rows.mean())),
                        (float(cols.max()), float(rows.mean())),
                    ),
                    STRUCTURE,
                    3,
                )
            ]
            legend = ["Amber line: long bright structure."]
        return summary, [], strokes, legend
    returns = waterline_returns(
        frame.db, water, mode, frame.col_m, frame.row_m, excluded
    )
    summary = [{"label": "Bright returns", "value": str(len(returns))}]
    strokes = [Stroke(((item.col, item.row),), MARK) for item in returns]
    return summary, [], strokes, ["Cyan marker: bright return."]


def _run_motion(scene_id: str, on_step: OnStep) -> None:
    sentences = step_sentences("dwell-motion")
    on_step(1, sentences[0])
    frame = _load_frame(scene_id)
    on_step(2, sentences[1])
    folder = scene_dir(scene_id)
    video, video_scale = load_video(folder / "vid-cog.tif")
    video_meta = read_json(folder / "vid-json.json")
    properties = _properties(video_meta)
    video_grid = Grid.from_transform(_transform(properties))
    stac_props = _properties(read_json(folder / "stac.json"))
    dwell_s = dwell_seconds(stac_props) or 1.0
    on_step(3, sentences[2])
    water, mode = water_mask(frame.db)
    returns = waterline_returns(frame.db, water, mode, frame.col_m, frame.row_m)
    centres: list[tuple[float, float]] = []
    for item in returns:
        lon, lat = frame.grid.to_lonlat(item.col, item.row, frame.scale)
        col, row = video_grid.to_colrow(lon, lat, video_scale)
        centres.append((row, col))
    on_step(4, sentences[3])
    tracks = track_returns(
        video, centres, 1.0, 1.0, min(frame.col_m, frame.row_m), dwell_s
    )
    on_step(5, sentences[4])
    strokes: list[Stroke] = []
    moved = 0
    for track in tracks:
        raw = track["points"]
        if not isinstance(raw, list) or len(raw) < 2:
            continue
        mapped: list[tuple[float, float]] = []
        for point in raw:
            if not isinstance(point, tuple):
                continue
            vrow, vcol = float(point[0]), float(point[1])
            lon, lat = video_grid.to_lonlat(vcol, vrow, video_scale)
            col, row = frame.grid.to_colrow(lon, lat, frame.scale)
            mapped.append((col, row))
        color = MOVED if track["motion"] == "moved" else MARK
        if track["motion"] == "moved":
            moved += 1
        strokes.append(Stroke(tuple(mapped), color, 2))
    summary = [
        {"label": "Returns tracked", "value": str(len(tracks))},
        {"label": "Moved during the dwell", "value": str(moved)},
        {"label": "Dwell", "value": f"{dwell_s:.1f} s"},
    ]
    legend = [
        f"Backdrop is sigma-nought, {frame.low:.0f} to {frame.high:.0f} dB.",
        "Cyan track: stationary during the dwell.",
        "Red track: moved during the dwell.",
        LIMITS["dwell-motion"],
    ]
    image = render(stretch(frame.db, frame.low, frame.high), [], strokes, legend)
    on_step(6, sentences[5])
    _write(
        scene_id, "dwell-motion", None, summary, legend, image, LIMITS["dwell-motion"]
    )


def _run_change(scene_id: str, partner_id: str, on_step: OnStep) -> None:
    sentences = step_sentences("amplitude-change")
    on_step(1, sentences[0])
    primary = _load_frame(scene_id)
    other = _load_frame(partner_id)
    on_step(2, sentences[1])
    warped = np.asarray(
        warp_affine(
            other.db,
            other.grid,
            other.scale,
            primary.db.shape,
            primary.grid,
            primary.scale,
        ),
        dtype=np.float32,
    )
    earlier, later, earlier_id, later_id = _order(primary, other, warped)
    on_step(3, sentences[2])
    darker, brighter = change_masks(earlier, later)
    pixel_area = primary.col_m * primary.row_m
    on_step(4, sentences[3])
    low, high = percentile_range(np.concatenate([earlier.ravel(), later.ravel()]))
    earlier_u8 = (np.nan_to_num(stretch(earlier, low, high)) * 255).astype(np.uint8)
    later_u8 = (np.nan_to_num(stretch(later, low, high)) * 255).astype(np.uint8)
    composite = np.dstack([earlier_u8, later_u8, later_u8])
    image = with_legend(
        _rgb_image(composite),
        [
            f"Shared stretch {low:.0f} to {high:.0f} dB.",
            f"Red: {earlier_id} (earlier). Cyan: {later_id} (later).",
            "Red has fled. Cyan is new.",
            LIMITS["amplitude-change"],
        ],
    )
    stable = ~darker & ~brighter & np.isfinite(earlier) & np.isfinite(later)
    summary = [
        {"label": "Earlier scene", "value": earlier_id},
        {"label": "Later scene", "value": later_id},
        {
            "label": "Darker area",
            "value": f"{float(darker.sum()) * pixel_area / 1e6:.2f} km²",
        },
        {
            "label": "Brighter area",
            "value": f"{float(brighter.sum()) * pixel_area / 1e6:.2f} km²",
        },
        {
            "label": "Unchanged area",
            "value": (
                f"{float(stable.sum()) * pixel_area / 1e6:.2f} km²"
            ),
        },
    ]
    on_step(5, sentences[4])
    _write(
        scene_id,
        "amplitude-change",
        partner_id,
        summary,
        ["Red has fled. Cyan is new."],
        image,
        LIMITS["amplitude-change"],
    )


def _run_stack(
    scene_id: str,
    tool_id: str,
    partners: tuple[str, ...],
    on_step: OnStep,
) -> None:
    sentences = step_sentences(tool_id)
    on_step(1, sentences[0])
    primary = _load_frame(scene_id)
    on_step(2, sentences[1])
    frames = [primary]
    aligned = [primary.db]
    for partner_id in partners:
        other = _load_frame(partner_id)
        warped = np.asarray(
            warp_affine(
                other.db,
                other.grid,
                other.scale,
                primary.db.shape,
                primary.grid,
                primary.scale,
            ),
            dtype=np.float32,
        )
        frames.append(
            Frame(
                other.scene_id,
                other.collected_at,
                warped,
                primary.grid,
                primary.scale,
                primary.col_m,
                primary.row_m,
                other.low,
                other.high,
            )
        )
        aligned.append(warped)
    on_step(3, sentences[2])
    order = sorted(range(len(frames)), key=lambda index: frames[index].collected_at)
    frames = [frames[index] for index in order]
    aligned = [aligned[index] for index in order]
    gray = stretch(primary.db, primary.low, primary.high)
    image, summary, legend = _stack_picture(tool_id, primary, frames, aligned, gray)
    on_step(4, sentences[3])
    on_step(5, sentences[4])
    _write(scene_id, tool_id, None, summary, legend, image, LIMITS[tool_id])


def _stack_picture(
    tool_id: str,
    primary: Frame,
    frames: list[Frame],
    aligned: list[np.ndarray],
    gray: np.ndarray,
) -> tuple[Image.Image, list[dict[str, str]], list[str]]:
    masks = [water_mask(frame)[0] for frame in aligned]
    modes = [frame_mode(frame) for frame in aligned]
    dates = [_short_date(frame.collected_at) for frame in frames]
    legend = [f"Stack of {len(frames)} dates, same orbit direction and look side."]
    if tool_id == "water-persistence":
        fraction = persistence(masks)
        summary = [
            {"label": "Dates", "value": str(len(frames))},
            {"label": "Mean water fraction", "value": f"{float(fraction.mean()):.3f}"},
        ]
        image = _fraction_image(gray, fraction, WATER)
        legend += ["Blue strength: water on N of M dates.", LIMITS[tool_id]]
        return with_legend(image, legend), summary, legend
    if tool_id == "sea-state":
        levels = sea_state(aligned, masks)
        summary = [
            {"label": dates[index], "value": _db_text(level)}
            for index, level in enumerate(levels)
        ]
        base = render(
            gray, [MaskLayer(masks[frames.index(primary)], WATER, 0.25)], [], []
        )
        legend += [LIMITS[tool_id]]
        return attach_bars(with_legend(base, legend), dates, levels), summary, legend
    if tool_id == "dark-sea-anomaly":
        median = stack_median(aligned)
        water, _mode = water_mask(primary.db)
        anomaly = dark_anomaly(primary.db, median, water)
        summary = [{"label": "Anomaly area", "value": _km2(anomaly, primary)}]
        legend += [
            "Yellow: dark sea anomaly on this date.",
            LIMITS[tool_id],
        ]
        image = render(gray, [MaskLayer(anomaly, ANOMALY, 0.55)], [], legend)
        return image, summary, legend
    if tool_id == "shoreline-series":
        layers = [
            MaskLayer(shoreline(mask), DATE_COLORS[index % len(DATE_COLORS)], 0.9)
            for index, mask in enumerate(masks)
        ]
        summary = [{"label": "Dates", "value": str(len(frames))}]
        legend += [LIMITS[tool_id]]
        return render(gray, layers, [], legend), summary, legend
    if tool_id == "date-of-change":
        which, keep = date_of_change(aligned)
        summary = [{"label": "Changed fraction", "value": f"{float(keep.mean()):.3f}"}]
        image = _index_image(gray, which, keep)
        legend += [
            f"{DATE_COLORS[index % len(DATE_COLORS)]}: {dates[index]}"
            for index in range(len(dates))
        ]
        legend.append(LIMITS[tool_id])
        return with_legend(image, legend), summary, legend
    if tool_id == "repeat-returns":
        counted = repeat_counts(aligned, masks, modes, primary.col_m, primary.row_m)
        once = sum(1 for _row, _col, count in counted if count == 1)
        many = sum(1 for _row, _col, count in counted if count > 1)
        strokes = [
            Stroke(
                ((col, row),),
                MARK if count == 1 else MOVED,
            )
            for row, col, count in counted
        ]
        summary = [
            {"label": "Seen once", "value": str(once)},
            {"label": "Seen on many dates", "value": str(many)},
        ]
        legend += [
            "Cyan: one date.",
            "Red: many dates.",
            LIMITS[tool_id],
        ]
        return render(gray, [], strokes, legend), summary, legend
    if tool_id == "site-activity":
        median = stack_median(aligned)
        mode = frame_mode(primary.db)
        appeared, left = site_activity(primary.db, median, mode)
        summary = [
            {"label": "New bright area", "value": _km2(appeared, primary)},
            {"label": "Missing bright area", "value": _km2(left, primary)},
        ]
        legend += [
            "Cyan: new on this date.",
            "Red: missing on this date.",
            LIMITS[tool_id],
        ]
        image = render(
            gray,
            [MaskLayer(appeared, NEW), MaskLayer(left, GONE)],
            [],
            legend,
        )
        return image, summary, legend
    mean = stack_mean(aligned)
    low, high = percentile_range(mean)
    summary = [{"label": "Dates averaged", "value": str(len(frames))}]
    legend = [
        f"Mean sigma-nought, {low:.0f} to {high:.0f} dB.",
        f"{len(frames)} dates averaged.",
        LIMITS[tool_id],
    ]
    image = render(stretch(mean, low, high), [], [], legend)
    return image, summary, legend


def _load_frame(scene_id: str) -> Frame:
    folder = scene_dir(scene_id)
    meta = read_json(folder / "grd-json.json")
    properties = _properties(meta)
    grid = Grid.from_transform(_transform(properties))
    amplitude, scale = load_amplitude(folder / "grd-cog.tif")
    factor = calibration_factor(meta, scene_id)
    if factor is None:
        raise RuntimeError(
            "This GRD sidecar has no calibration factor, "
            "so sigma-nought is not available."
        )
    db = sigma0_db(amplitude, factor)
    col_m, row_m = pixel_metres(grid, scale)
    low, high = percentile_range(db)
    stac = read_json(folder / "stac.json")
    collected = _properties(stac).get("datetime")
    return Frame(
        scene_id,
        collected if isinstance(collected, str) else scene_id,
        db,
        grid,
        scale,
        col_m,
        row_m,
        low,
        high,
    )


def _write(
    scene_id: str,
    tool_id: str,
    partner_id: str | None,
    summary: list[dict[str, str]],
    legend: list[str],
    image: object,
    limit: str,
) -> None:
    folder = analysis_dir(scene_id, tool_id, partner_id)
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "tool_id": tool_id,
        "scene_id": scene_id,
        "partner_id": partner_id,
        "summary": summary,
        "limit": limit,
    }
    (folder / "measurements.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    lines = [f"# {tool_spec(tool_id).label}", "", limit, ""]
    for row in summary:
        lines.append(f"- {row['label']}: {row['value']}")
    lines.append("")
    (folder / "briefing.md").write_text("\n".join(lines), encoding="utf-8")
    if hasattr(image, "save"):
        image.save(folder / "overview.png")
    del legend


def _order(
    primary: Frame, other: Frame, warped: np.ndarray
) -> tuple[np.ndarray, np.ndarray, str, str]:
    if other.collected_at <= primary.collected_at:
        return warped, primary.db, other.scene_id, primary.scene_id
    return primary.db, warped, primary.scene_id, other.scene_id


def _fraction_image(
    gray: np.ndarray, fraction: np.ndarray, color: Color
) -> Image.Image:
    rgb = np.dstack([gray, gray, gray])
    alpha = np.clip(fraction, 0, 1)[..., None] * 0.75
    paint = np.array(color, dtype=np.float32) / 255
    mixed = rgb * (1 - alpha) + paint * alpha
    return Image.fromarray((np.clip(mixed, 0, 1) * 255).astype(np.uint8), mode="RGB")


def _index_image(gray: np.ndarray, which: np.ndarray, keep: np.ndarray) -> Image.Image:
    rgb = np.dstack([gray, gray, gray])
    for index, color in enumerate(DATE_COLORS):
        mask = keep & (which % len(DATE_COLORS) == index)
        if not mask.any():
            continue
        paint = np.array(color, dtype=np.float32) / 255
        rgb[mask] = 0.35 * rgb[mask] + 0.65 * paint
    return _rgb_image((rgb * 255).astype(np.uint8))


def _rgb_image(array: np.ndarray) -> Image.Image:
    return Image.fromarray(array, mode="RGB")


def _median(db: np.ndarray, mask: np.ndarray) -> float | None:
    values = db[mask & np.isfinite(db)]
    if values.size == 0:
        return None
    return float(np.median(values))


def _db_text(value: float | None) -> str:
    if value is None:
        return "none"
    return f"{value:.1f} dB"


def _km2(mask: np.ndarray, frame: Frame) -> str:
    return f"{float(mask.sum()) * frame.col_m * frame.row_m / 1e6:.2f} km²"


def _count_parts(mask: np.ndarray) -> tuple[np.ndarray, int]:
    from scipy import ndimage

    labels, count = ndimage.label(mask)
    return labels, int(count)


def _properties(payload: dict[str, object]) -> dict[str, object]:
    properties = payload.get("properties")
    if isinstance(properties, dict):
        return properties
    return {}


def _transform(properties: dict[str, object]) -> list[float]:
    raw = properties.get("proj:transform")
    if not isinstance(raw, list) or len(raw) < 6:
        raise RuntimeError("grd-json.json has no proj:transform")
    return [float(value) for value in raw[:6]]


def _short_date(value: str) -> str:
    return value[:10] if len(value) >= 10 else value
