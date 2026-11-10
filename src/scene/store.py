"""Move a flat ``data/`` checkout into ``data/scenes/<id>/``.

The first Lisbon download wrote ``stac.json`` and the rasters directly
into ``data/``. A second scene would have overwritten those names. This
module renames that checkout into the scene folder. Rename stays on the
same filesystem, so the large rasters are not copied.
"""

from __future__ import annotations

import json
from pathlib import Path

from .naming import local_asset_name
from .paths import data_dir, valid_scene_id


def migrate_flat_scene(root: Path | None = None) -> Path | None:
    """Move ``root/stac.json`` and its asset files into ``root/scenes/<id>/``.

    Returns the scene directory, or None when there is no flat record.
    A file already present in the destination with the same size is kept
    and the flat copy is removed. A destination with a different size is
    left untouched, and the flat file stays where it is.
    """

    data = root if root is not None else data_dir()
    source = data / "stac.json"
    if not source.is_file():
        return None

    scene_id = _scene_id(source)
    if not valid_scene_id(scene_id):
        raise ValueError(f"Refusing to migrate unsafe scene id: {scene_id}")

    destination = data / "scenes" / scene_id
    destination.mkdir(parents=True, exist_ok=True)
    payload = json.loads(source.read_text(encoding="utf-8"))
    assets = payload.get("assets") if isinstance(payload, dict) else None
    if isinstance(assets, dict):
        for key, raw in assets.items():
            if not isinstance(key, str) or not isinstance(raw, dict):
                continue
            href = raw.get("href")
            if not isinstance(href, str) or not href:
                continue
            _relocate(data / local_asset_name(key, href), destination)
    _relocate(source, destination)
    return destination


def _scene_id(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a STAC item object")
    scene_id = payload.get("id")
    if not isinstance(scene_id, str) or not scene_id.strip():
        raise ValueError(f"{path} id must be a non-empty string")
    return scene_id


def _relocate(source: Path, destination_dir: Path) -> None:
    if not source.is_file():
        return
    target = destination_dir / source.name
    # scene_dir() is the public check. Migration builds the same path
    # from an id that has already passed valid_scene_id.
    if target.exists():
        if target.is_file() and target.stat().st_size == source.stat().st_size:
            source.unlink()
        return
    source.rename(target)

