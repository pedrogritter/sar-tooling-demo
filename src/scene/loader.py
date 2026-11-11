"""Load one STAC item and the local asset files that sit beside it.

``python -m scene.fetch`` writes ``data/scenes/<id>/stac.json`` and names
each kept asset ``{asset-key}{suffix}`` (for example ``qlk-cog.tif``).
This module uses that same naming so the page can only open files that
command saved. The default path is the Lisbon test scene. A flat
``data/stac.json`` checkout is moved into that folder on first read.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard

from .naming import local_asset_name
from .paths import FETCH_COMMAND, LISBON_SCENE_ID, scene_dir

# Fields the page is allowed to treat as facts about the collect.
_REQUIRED_STRINGS = (
    "datetime",
    "start_datetime",
    "end_datetime",
    "platform",
    "sar:instrument_mode",
    "sar:frequency_band",
    "sat:orbit_state",
)


class SceneDataError(Exception):
    """The on-disk STAC record is missing or does not match this reader."""


@dataclass(frozen=True)
class BoundingBox:
    """STAC bbox order: west, south, east, north, in degrees."""

    west: float
    south: float
    east: float
    north: float


@dataclass(frozen=True)
class Asset:
    """One STAC asset. ``local_path`` is set only when the file is on disk."""

    key: str
    title: str
    media_type: str
    href: str
    local_path: Path | None

    @property
    def on_disk(self) -> bool:
        return self.local_path is not None


@dataclass(frozen=True)
class SceneRecord:
    """The collect metadata this demo is allowed to show."""

    scene_id: str
    collected_at: str
    start_at: str
    end_at: str
    platform: str
    mode: str
    band: str
    polarizations: tuple[str, ...]
    orbit_state: str
    incidence_angle: float
    bbox: BoundingBox
    assets: tuple[Asset, ...]

    def asset(self, key: str) -> Asset | None:
        for item in self.assets:
            if item.key == key:
                return item
        return None


def default_stac_path() -> Path:
    """Path of the Lisbon STAC item ``python -m scene.fetch`` writes.

    A checkout that still has ``data/stac.json`` is migrated first, so the
    rasters already on disk stay the test scene.
    """

    from .store import migrate_flat_scene

    migrate_flat_scene()
    return scene_dir(LISBON_SCENE_ID) / "stac.json"


def load_scene(stac_path: Path | None = None) -> SceneRecord:
    """Read ``stac.json`` and pair each asset with a local file if it exists.

    Raises SceneDataError with a message that says what to run when the
    file is absent or a required field is the wrong type. Missing large
    products are not an error: their ``local_path`` stays None.
    """

    path = stac_path or default_stac_path()
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise SceneDataError(f"{path} must contain a STAC item object")

    scene_id = _require_text(payload.get("id"), f"{path} id")
    properties = payload.get("properties")
    if not isinstance(properties, dict):
        raise SceneDataError(f"{path} properties must be an object")

    values = {
        key: _require_text(properties.get(key), f"{path} properties.{key}")
        for key in _REQUIRED_STRINGS
    }
    bbox = _require_bbox(payload.get("bbox"), path)
    assets_raw = payload.get("assets")
    if not isinstance(assets_raw, dict) or not assets_raw:
        raise SceneDataError(f"{path} assets must be a non-empty object")

    return SceneRecord(
        scene_id=scene_id,
        collected_at=values["datetime"],
        start_at=values["start_datetime"],
        end_at=values["end_datetime"],
        platform=values["platform"],
        mode=values["sar:instrument_mode"],
        band=values["sar:frequency_band"],
        polarizations=_require_polarizations(properties.get("sar:polarizations"), path),
        orbit_state=values["sat:orbit_state"],
        incidence_angle=_require_number(
            properties.get("view:incidence_angle"),
            f"{path} properties.view:incidence_angle",
        ),
        bbox=bbox,
        assets=tuple(
            _load_asset(key, raw, path.parent) for key, raw in assets_raw.items()
        ),
    )


def _read_json(path: Path) -> object:
    if not path.is_file():
        raise SceneDataError(
            f"Missing {path}. From the repository root, run: {FETCH_COMMAND}"
        )
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SceneDataError(f"{path} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise SceneDataError(f"Could not read {path}: {exc}") from exc


def _load_asset(key: str, raw: object, data_dir: Path) -> Asset:
    if not isinstance(key, str) or not key:
        raise SceneDataError("STAC asset keys must be non-empty strings")
    if not isinstance(raw, dict):
        raise SceneDataError(f"Asset {key} must be an object")
    href = _require_text(raw.get("href"), f"assets.{key}.href")
    title = raw.get("title")
    media_type = raw.get("type")
    local_path = data_dir / _local_name(key, href)
    return Asset(
        key=key,
        title=title if isinstance(title, str) and title else key,
        media_type=media_type if isinstance(media_type, str) else "",
        href=href,
        local_path=local_path if _file_inside(data_dir, local_path) else None,
    )


def _local_name(key: str, href: str) -> str:
    """Match the filenames ``scene.fetch`` writes for the assets it keeps."""

    return local_asset_name(key, href)


def _require_bbox(raw: object, path: Path) -> BoundingBox:
    if (
        not isinstance(raw, list)
        or len(raw) != 4
        or any(not _is_number(value) for value in raw)
    ):
        raise SceneDataError(
            f"{path} bbox must be four numbers: west, south, east, north"
        )
    west, south, east, north = (float(value) for value in raw)
    if not all(math.isfinite(value) for value in (west, south, east, north)):
        raise SceneDataError(f"{path} bbox must be finite degrees")
    if west >= east or south >= north:
        raise SceneDataError(f"{path} bbox is empty or inverted")
    return BoundingBox(west=west, south=south, east=east, north=north)


def _file_inside(directory: Path, candidate: Path) -> bool:
    """True when ``candidate`` is a file and stays inside ``directory``.

    An asset key such as ``../secret`` must not count a file outside the
    scene folder as a product of this collect.
    """

    if not candidate.is_file():
        return False
    try:
        candidate.resolve().relative_to(directory.resolve())
    except (OSError, ValueError):
        return False
    return True


def _require_polarizations(raw: object, path: Path) -> tuple[str, ...]:
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(value, str) or not value for value in raw)
    ):
        raise SceneDataError(
            f"{path} properties.sar:polarizations must be a non-empty list of strings"
        )
    return tuple(raw)


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SceneDataError(f"{label} must be a non-empty string")
    return value


def _require_number(value: object, label: str) -> float:
    if not _is_number(value):
        raise SceneDataError(f"{label} must be a number")
    return float(value)


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
