"""Asset filenames shared by fetch, the loader, and downloads.

``python -m scene.fetch`` saves each kept asset as ``{key}{suffix}``
beside ``stac.json``. The loader pairs files by that same rule, so a
download job has to use it too.
"""

from __future__ import annotations

from pathlib import Path


def local_asset_name(key: str, href: str) -> str:
    """Filename for one STAC asset. Query strings are ignored."""

    suffix = Path(href.split("?", 1)[0]).suffix
    return f"{key}{suffix}"
