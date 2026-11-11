"""Which tools the open scene can run, and the one sentence that locks the rest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scene.demo import note_from_folder
from scene.jobs import read_job_result
from scene.loader import SceneDataError, load_scene
from scene.paths import scene_dir, valid_scene_id

from .geometry import INCIDENCE_TOLERANCE, Collect, can_pair, is_calibrated_mode
from .raster import calibration_factor, read_json

STACK_MIN = 2
STACK_MEAN_MIN = 5


@dataclass(frozen=True)
class ToolSpec:
    id: str
    label: str
    category: str
    description: str
    kind: str


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "open-water",
        "Open water",
        "Surface",
        "Dark smooth water. Area, fraction, and median sigma-nought.",
        "single",
    ),
    ToolSpec(
        "sea-roughness",
        "Sea roughness",
        "Surface",
        "Calm water against wind-roughened water, inside the water mask.",
        "single",
    ),
    ToolSpec(
        "built-up",
        "Built-up return",
        "Surface",
        "Bright clusters on land. Fraction of land and a cluster count.",
        "single",
    ),
    ToolSpec(
        "returns-on-water",
        "Returns on water",
        "Objects",
        "Compact bright returns that touch the water. The label stays bright return.",
        "single",
    ),
    ToolSpec(
        "long-structure",
        "Long structure",
        "Objects",
        "A long bright return along the waterline. "
        "Length, width, and peak sigma-nought.",
        "single",
    ),
    ToolSpec(
        "dwell-motion",
        "Dwell motion",
        "Motion",
        "Tracks of bright returns during the dwell. Displacement and speed.",
        "motion",
    ),
    ToolSpec(
        "amplitude-change",
        "Amplitude change",
        "Change",
        "Earlier date in red, later date in cyan. Needs the same look.",
        "pair",
    ),
    ToolSpec(
        "water-persistence",
        "Water persistence",
        "Stack",
        "How many dates each pixel is water.",
        "stack",
    ),
    ToolSpec(
        "sea-state",
        "Sea state",
        "Stack",
        "Median sigma-nought of the water on each date.",
        "stack",
    ),
    ToolSpec(
        "dark-sea-anomaly",
        "Dark sea anomaly",
        "Stack",
        "A patch darker than the stack median of the sea. Extent only, not a spill.",
        "stack",
    ),
    ToolSpec(
        "shoreline-series",
        "Shoreline",
        "Stack",
        "The waterline once per date.",
        "stack",
    ),
    ToolSpec(
        "date-of-change",
        "Date of change",
        "Stack",
        "The date a pixel left the stack median, when the departure exceeds 1.5 dB.",
        "stack",
    ),
    ToolSpec(
        "repeat-returns",
        "Repeat returns",
        "Stack",
        "A bright return seen on many dates against one seen on a single date.",
        "stack",
    ),
    ToolSpec(
        "site-activity",
        "Site activity",
        "Stack",
        "A bright cluster that appears or leaves relative to the stack median.",
        "stack",
    ),
    ToolSpec(
        "stack-mean",
        "Stack mean",
        "Stack",
        "The mean of the matched dates. The caption names how many were averaged.",
        "stack-mean",
    ),
)


@dataclass(frozen=True)
class ToolView:
    id: str
    label: str
    category: str
    description: str
    locked: bool
    reason: str
    needs_partner: bool
    partners: tuple[str, ...]
    overview_url: str | None
    measurement: object | None
    briefing_html: str | None

    def to_public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "category": self.category,
            "description": self.description,
            "locked": self.locked,
            "reason": self.reason,
            "needs_partner": self.needs_partner,
            "partners": list(self.partners),
            "overview_url": self.overview_url,
            "measurement": self.measurement,
            "briefing_html": self.briefing_html,
        }


def tool_spec(tool_id: str) -> ToolSpec:
    for spec in TOOLS:
        if spec.id == tool_id:
            return spec
    raise KeyError(tool_id)


def tools_for_scene(scene_id: str) -> list[ToolView]:
    """Lock state for every tool, using scenes already on disk."""

    current = _collect(scene_id)
    others = [item for item in _library() if item.scene_id != scene_id]
    matches = tuple(item.scene_id for item in others if can_pair(current, item))
    views: list[ToolView] = []
    note = note_from_folder(scene_dir(scene_id))
    for spec in TOOLS:
        locked, reason = _lock(spec, current, matches)
        if locked and note:
            reason = f"{note} {reason}"
        partner = spec.kind == "pair"
        saved = _saved_result(scene_id, spec.id)
        views.append(
            ToolView(
                id=spec.id,
                label=spec.label,
                category=spec.category,
                description=spec.description,
                locked=locked,
                reason="" if not locked else reason,
                needs_partner=partner,
                partners=matches
                if spec.kind in {"pair", "stack", "stack-mean"}
                else (),
                overview_url=_overview_url(scene_id, spec.id),
                measurement=saved[0],
                briefing_html=saved[1],
            )
        )
    return views


def analysis_dir(scene_id: str, tool_id: str, partner_id: str | None = None) -> Path:
    folder = scene_dir(scene_id) / "analysis" / tool_id
    if partner_id:
        return folder / partner_id
    return folder


def _lock(
    spec: ToolSpec, current: Collect, matches: tuple[str, ...]
) -> tuple[bool, str]:
    if not current.has_grd:
        return True, "This tool reads grd-cog.tif. It is not in this scene folder."
    if spec.kind == "motion":
        if not current.has_vid:
            return (
                True,
                "Dwell motion reads vid-cog.tif. This collect has no dwell stack.",
            )
        if not current.calibrated:
            return _uncalibrated(current)
        return False, ""
    if not current.calibrated:
        return _uncalibrated(current)
    if spec.kind in {"pair", "stack", "stack-mean"} and (
        not current.orbit or not current.look
    ):
        return (
            True,
            "This scene record has no orbit direction or look side, "
            "so a pair cannot be checked.",
        )
    if spec.kind == "pair":
        if not matches:
            return (
                True,
                "Amplitude change needs a second calibrated scene with "
                f"{_same_look()}, and grd-cog.tif on disk.",
            )
        return False, ""
    if spec.kind == "stack" and len(matches) + 1 < STACK_MIN:
        return (
            True,
            "This stack tool needs at least one other calibrated scene with "
            f"{_same_look()}, and grd-cog.tif on disk.",
        )
    if spec.kind == "stack-mean" and len(matches) + 1 < STACK_MEAN_MIN:
        return (
            True,
            "The stack mean needs five calibrated scenes that share "
            f"{_same_look()}.",
        )
    return False, ""


def _same_look() -> str:
    """The pairing clause. The number is the tolerance ``can_pair`` enforces."""

    span = f"{INCIDENCE_TOLERANCE:g}"
    unit = "degree" if INCIDENCE_TOLERANCE == 1 else "degrees"
    return (
        "the same orbit direction, the same look side, and an incidence "
        f"angle within {span} {unit}"
    )


def _uncalibrated(current: Collect) -> tuple[bool, str]:
    if not is_calibrated_mode(current.mode):
        return (
            True,
            "Scan and Scan Wide GRDs are not radiometrically calibrated, "
            "so this tool does not report sigma-nought.",
        )
    return (
        True,
        "This GRD sidecar has no calibration factor, so sigma-nought is not available.",
    )


def _saved_result(scene_id: str, tool_id: str) -> tuple[object | None, str | None]:
    """Summary and briefing already written for this tool, if the files exist."""

    folder = _result_dir(scene_id, tool_id)
    if folder is None:
        return None, None
    result = read_job_result(folder, _overview_url(scene_id, tool_id) or "")
    return result.measurement, result.briefing_html


def _result_dir(scene_id: str, tool_id: str) -> Path | None:
    folder = analysis_dir(scene_id, tool_id)
    if (folder / "measurements.json").is_file() or (folder / "overview.png").is_file():
        return folder
    if not folder.is_dir():
        return None
    for child in sorted(folder.iterdir()):
        saved = (child / "measurements.json").is_file()
        picture = (child / "overview.png").is_file()
        if child.is_dir() and (saved or picture):
            return child
    return None


def _overview_url(scene_id: str, tool_id: str) -> str | None:
    folder = analysis_dir(scene_id, tool_id)
    direct = folder / "overview.png"
    if direct.is_file():
        return f"/api/scenes/{scene_id}/analysis/{tool_id}/overview.png"
    if not folder.is_dir():
        return None
    for child in sorted(folder.iterdir()):
        if child.is_dir() and (child / "overview.png").is_file():
            return (
                f"/api/scenes/{scene_id}/analysis/{tool_id}/{child.name}/overview.png"
            )
    return None


def _library() -> list[Collect]:
    root = scene_dir(LISBON_SAFE).parent
    found: list[Collect] = []
    if not root.is_dir():
        return found
    for child in root.iterdir():
        if (
            child.is_dir()
            and valid_scene_id(child.name)
            and (child / "stac.json").is_file()
        ):
            try:
                found.append(_collect(child.name))
            except (OSError, SceneDataError, RuntimeError, KeyError, ValueError):
                continue
    return found


# scene_dir() rejects a bad id. The scenes root is the parent of any valid id.
LISBON_SAFE = "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF"


def _collect(scene_id: str) -> Collect:
    folder = scene_dir(scene_id)
    record = load_scene(folder / "stac.json")
    properties = _properties(folder / "stac.json")
    look = properties.get("sar:observation_direction")
    factor = _factor(folder, scene_id)
    mode = record.mode
    calibrated = is_calibrated_mode(mode) and factor is not None
    grd = record.asset("grd-cog")
    vid = record.asset("vid-cog")
    bbox = record.bbox
    return Collect(
        scene_id=record.scene_id,
        collected_at=record.collected_at,
        mode=mode,
        orbit=record.orbit_state,
        look=look if isinstance(look, str) else "",
        incidence=record.incidence_angle,
        bbox=(bbox.west, bbox.south, bbox.east, bbox.north),
        has_grd=grd is not None and grd.on_disk,
        has_vid=vid is not None and vid.on_disk,
        calibrated=calibrated,
    )


def _factor(folder: Path, scene_id: str) -> float | None:
    path = folder / "grd-json.json"
    if not path.is_file():
        return calibration_factor({}, scene_id)
    return calibration_factor(read_json(path), scene_id)


def _properties(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    properties = payload.get("properties")
    if isinstance(properties, dict):
        return properties
    return {}
