"""List scenes already on disk by reading each ``stac.json``.

There is no second database. A folder counts when it contains a STAC item
this reader accepts. The Lisbon collect is marked as the test scene.
"""

from __future__ import annotations

from pathlib import Path

from .loader import Asset, SceneDataError, SceneRecord, load_scene
from .paths import LISBON_SCENE_ID, data_dir, valid_scene_id


def list_library(root: Path | None = None) -> list[dict[str, object]]:
    """Scan ``data/scenes/*/stac.json``. Broken folders are skipped."""

    scenes = (root if root is not None else data_dir()) / "scenes"
    if not scenes.is_dir():
        return []
    base = scenes.resolve()
    entries: list[dict[str, object]] = []
    for child in scenes.iterdir():
        if not child.is_dir() or not valid_scene_id(child.name):
            continue
        try:
            if not child.resolve().is_relative_to(base):
                continue
        except (OSError, ValueError):
            continue
        stac = child / "stac.json"
        if not stac.is_file():
            continue
        try:
            scene = load_scene(stac)
        except SceneDataError:
            continue
        entries.append(_entry(scene))
    entries.sort(key=lambda entry: str(entry["collected_at"]), reverse=True)
    entries.sort(key=lambda entry: not bool(entry["is_test_scene"]))
    return entries


def _entry(scene: SceneRecord) -> dict[str, object]:
    scene_id = scene.scene_id
    graphic = scene.asset("graphic")
    quicklook = scene.asset("qlk-cog")
    video = scene.asset("vid-mp4")
    has_quicklook = _on_disk(quicklook) or _on_disk(graphic)
    return {
        "scene_id": scene_id,
        "collected_at": scene.collected_at,
        "platform": scene.platform,
        "mode": scene.mode,
        "assets_on_disk": [asset.key for asset in scene.assets if asset.on_disk],
        "is_test_scene": scene_id == LISBON_SCENE_ID,
        "quicklook_url": (
            f"/api/scenes/{scene_id}/quicklook.png" if has_quicklook else None
        ),
        "thumbnail_url": (
            f"/api/scenes/{scene_id}/thumbnail" if _on_disk(graphic) else None
        ),
        "video_url": f"/api/scenes/{scene_id}/video" if _on_disk(video) else None,
    }


def _on_disk(asset: Asset | None) -> bool:
    return asset is not None and asset.on_disk
