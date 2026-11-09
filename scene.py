"""Download public assets for one ICEYE open-data scene.

By default this keeps the STAC record, the thumbnail, the quicklook, and
the dwell video. ``python3 scene.py --all`` also streams the GRD, the
colorized sub-aperture image, the georeferenced dwell stack, and the SLC.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen

STAC_URL = (
    "https://iceye-open-data-catalog.s3-us-west-2.amazonaws.com/"
    "stac-items/2025/10/"
    "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF.json"
)
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
KEEP = ("graphic", "qlk-cog", "qlk-json", "vid-mp4")


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with urlopen(STAC_URL, timeout=60) as response:
        item = json.load(response)
    (DATA / "stac.json").write_text(json.dumps(item, indent=2), encoding="utf-8")
    names = tuple(item["assets"]) if "--all" in sys.argv[1:] else KEEP
    for name in names:
        asset = item["assets"][name]
        target = DATA / f"{name}{suffix_for(asset['href'])}"
        fetch(asset["href"], target)
    props = item["properties"]
    print("scene", item["id"])
    print("when", props["datetime"])
    print("platform", props["platform"], "mode", props["sar:instrument_mode"])
    print("band", props["sar:frequency_band"], "pol", props["sar:polarizations"])
    print("bbox", item["bbox"])


def fetch(href: str, target: Path) -> None:
    """Stream one asset. A file that already has the remote size is kept.

    Large products are not read into memory. curl resumes a partial file.
    """

    remote = remote_size(href)
    local = target.stat().st_size if target.exists() else 0
    if remote > 0 and local == remote:
        print(f"keep {target.name}")
        return
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


def remote_size(href: str) -> int:
    request = Request(href, method="HEAD")
    with urlopen(request, timeout=60) as response:
        return int(response.headers.get("Content-Length") or 0)


def suffix_for(href: str) -> str:
    path = href.split("?", 1)[0]
    return Path(path).suffix or ""


if __name__ == "__main__":
    main()
