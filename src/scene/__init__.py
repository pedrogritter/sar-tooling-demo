"""Reader and page for one ICEYE open-data scene.

The package loads the STAC record already saved by ``python -m scene.fetch``.
It does not download imagery and it does not detect objects.
"""

from .loader import SceneDataError, load_scene

__all__ = ["SceneDataError", "load_scene"]
