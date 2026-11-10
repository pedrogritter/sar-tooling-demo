"""Repository locations shared by the reader, the measurement job, and the CLIs.

The package lives in ``src/scene``. These helpers climb to the repository
root so a scene checkout can keep its products beside the code without the
package name naming a city.
"""

from __future__ import annotations

import re
from pathlib import Path

# Printed when a required product is missing. The command is the same on
# every scene checkout.
FETCH_COMMAND = "python -m scene.fetch"

# The bridge measurement in analyze.py describes this collect only.
LISBON_SCENE_ID = "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF"

# Scene ids become directory names. Reject anything that could leave data/.
_SCENE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def project_root() -> Path:
    """Directory that contains ``pyproject.toml``, ``data/``, and ``frontend/``."""

    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return project_root() / "data"


def scenes_dir() -> Path:
    """One folder per downloaded STAC item, under ``data/scenes``."""

    return data_dir() / "scenes"


def valid_scene_id(scene_id: str) -> bool:
    """True when ``scene_id`` is safe to use as a single path segment."""

    return bool(_SCENE_ID.fullmatch(scene_id))


def scene_dir(scene_id: str) -> Path:
    """Directory for one scene. Raises ValueError when the id is not safe."""

    if not valid_scene_id(scene_id):
        raise ValueError(f"Invalid scene id: {scene_id}")
    return scenes_dir() / scene_id


def lisbon_scene_dir() -> Path:
    """Products for the 25 de Abril test scene."""

    return scene_dir(LISBON_SCENE_ID)


def catalog_index_path() -> Path:
    """Cached open-data search index. Lives under gitignored ``data/``."""

    return data_dir() / "catalog-index.json"


def intelligence_dir() -> Path:
    return project_root() / "intelligence"


def scene_note_path() -> Path:
    return project_root() / "content" / "scene_note.md"


def static_dir() -> Path:
    """Fallback page assets packaged with the Python viewer."""

    return Path(__file__).resolve().parent / "static"


def frontend_dist_dir() -> Path:
    return project_root() / "frontend" / "dist"
