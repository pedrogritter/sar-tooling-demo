"""Download public assets for the Lisbon ICEYE open-data scene.

By default this keeps the STAC record, the thumbnail, the quicklook, and
the dwell video. ``python -m scene.fetch --all`` also streams the GRD, the
colorized sub-aperture image, the georeferenced dwell stack, and the SLC.

Files land in ``data/scenes/<id>/``. The catalogue URL below is the scene
this checkout measures. Other open-data items are downloaded from the page,
which calls :func:`fetch` for each selected asset.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from scene.naming import local_asset_name
from scene.paths import scene_dir, valid_scene_id
from scene.store import migrate_flat_scene

STAC_URL = (
    "https://iceye-open-data-catalog.s3-us-west-2.amazonaws.com/"
    "stac-items/2025/10/"
    "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF.json"
)
KEEP = ("graphic", "qlk-cog", "qlk-json", "vid-mp4")


def main() -> None:
    # A flat data/ checkout is moved before this write, so the Lisbon
    # rasters already on disk are not fetched again.
    migrate_flat_scene()
    with urlopen(STAC_URL, timeout=60) as response:
        item = json.load(response)
    scene_id = item.get("id")
    if not isinstance(scene_id, str) or not valid_scene_id(scene_id):
        raise SystemExit(f"STAC item id is not a safe scene id: {scene_id!r}")
    folder = scene_dir(scene_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "stac.json").write_text(json.dumps(item, indent=2), encoding="utf-8")
    names = tuple(item["assets"]) if "--all" in sys.argv[1:] else KEEP
    for name in names:
        asset = item["assets"][name]
        target = folder / local_asset_name(name, asset["href"])
        fetch(asset["href"], target)
    props = item["properties"]
    print("scene", item["id"])
    print("when", props["datetime"])
    print("platform", props["platform"], "mode", props["sar:instrument_mode"])
    print("band", props["sar:frequency_band"], "pol", props["sar:polarizations"])
    print("bbox", item["bbox"])


def fetch(href: str, target: Path) -> str:
    """Stream one asset. A file that already has the remote size is kept.

    Large products are not read into memory. curl resumes a partial file.
    Returns ``kept`` when nothing was transferred, otherwise ``done``.
    """

    remote = remote_size(href)
    local = target.stat().st_size if target.exists() else 0
    if remote > 0 and local == remote:
        print(f"keep {target.name}")
        return "kept"
    print(f"fetch {target.name} ({remote / 1e6:.1f} MB)")
    subprocess.run(
        [
            "curl",
            "-L",
            "--fail",
            "--retry",
            "5",
            "--retry-all-errors",
            "--continue-at",
            "-",
            "--output",
            str(target),
            href,
        ],
        check=True,
    )
    return "done"


def remote_size(href: str) -> int:
    request = Request(href, method="HEAD")
    with urlopen(request, timeout=60) as response:
        return int(response.headers.get("Content-Length") or 0)


if __name__ == "__main__":
    main()
