"""Facts about the open scene that a report may state without running a tool.

Everything here is read from files already on disk: the scene folder, the
belt's tool locks, and the local catalogue index. Nothing opens a socket.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from scene.belt.catalog import _collect, tools_for_scene
from scene.belt.geometry import (
    MIN_OVERLAP,
    Collect,
    overlap_fraction,
    same_look,
)
from scene.belt.raster import load_amplitude, pixel_metres, read_json
from scene.catalog import CatalogRecord, _records_from_disk
from scene.grid import Grid
from scene.loader import load_scene
from scene.paths import catalog_index_path, scene_dir


@dataclass(frozen=True)
class ReportFacts:
    """What is true of the open scene, and which catalogue scenes could join it."""

    scene_id: str
    mode: str
    incidence: float
    orbit: str
    look: str
    band: str
    polarization: str
    collected_at: str
    # Ground size of one overview pixel: (column metres, row metres).
    overview_metres: tuple[float, float] | None
    # The public dicts from tools_for_scene, in tool order.
    tools: list[dict[str, object]]
    # Catalogue scenes that match the look but are not downloaded.
    catalogue_only: list[dict[str, str]]


def report_facts(
    scene_id: str, records: Sequence[CatalogRecord] | None = None
) -> ReportFacts:
    """Read the open scene's facts.

    ``records`` are catalogue rows. When omitted, the local index file is read
    if it exists. The catalogue service is never started, so no request is made.
    """

    folder = scene_dir(scene_id)
    scene = load_scene(folder / "stac.json")
    current = _collect(scene_id)
    catalogue = _local_records() if records is None else records
    return ReportFacts(
        scene_id=scene.scene_id,
        mode=scene.mode,
        incidence=scene.incidence_angle,
        orbit=current.orbit,
        look=current.look,
        band=scene.band,
        polarization=scene.polarizations[0],
        collected_at=scene.collected_at,
        overview_metres=_overview_metres(folder),
        tools=[view.to_public() for view in tools_for_scene(scene_id)],
        catalogue_only=_catalogue_only(current, catalogue),
    )


def _local_records() -> list[CatalogRecord]:
    """Rows from the cached index file. An absent or unreadable file gives none."""

    path = catalog_index_path()
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return _records_from_disk(payload)


def _catalogue_only(
    current: Collect, records: Sequence[CatalogRecord]
) -> list[dict[str, str]]:
    """Cached rows that share look and overlap, and have no scene folder."""

    found: list[dict[str, str]] = []
    for record in records:
        if record.scene_id == current.scene_id or not _usable(record):
            continue
        if scene_dir(record.scene_id).is_dir():
            continue
        if not _shares_geometry(current, record):
            continue
        found.append(
            {
                "scene_id": record.scene_id,
                "collected_at": record.acquired_at or "",
            }
        )
    return found


def _usable(record: CatalogRecord) -> bool:
    """A row can be compared only after its item JSON was cached."""

    return (
        record.cached
        and bool(record.orbit)
        and bool(record.look)
        and record.incidence_angle is not None
        and record.bbox is not None
    )


def _shares_geometry(current: Collect, record: CatalogRecord) -> bool:
    """Same look and enough overlap. Calibration and files are not asked here."""

    assert record.bbox is not None and record.incidence_angle is not None
    other = Collect(
        scene_id=record.scene_id,
        collected_at=record.acquired_at or "",
        mode=record.mode or "",
        orbit=record.orbit or "",
        look=record.look or "",
        incidence=record.incidence_angle,
        bbox=record.bbox,
        has_grd=False,
        has_vid=False,
        calibrated=False,
    )
    if not same_look(current, other):
        return False
    return overlap_fraction(current.bbox, other.bbox) >= MIN_OVERLAP


def _overview_metres(folder: Path) -> tuple[float, float] | None:
    """Pixel size from the GRD sidecar's grid. None when either file is absent."""

    sidecar = folder / "grd-json.json"
    raster = folder / "grd-cog.tif"
    if not sidecar.is_file() or not raster.is_file():
        return None
    properties = read_json(sidecar).get("properties")
    transform = (
        properties.get("proj:transform") if isinstance(properties, dict) else None
    )
    if not isinstance(transform, list) or len(transform) < 6:
        return None
    _, scale = load_amplitude(raster)
    return pixel_metres(Grid.from_transform(transform), scale)
