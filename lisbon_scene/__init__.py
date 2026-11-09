"""Reader and page for one ICEYE open-data scene of Lisbon.

The package loads the STAC record already saved by ``scene.py``. It does
not download imagery and it does not detect objects.
"""

from .loader import SceneDataError, load_scene

__all__ = ["SceneDataError", "load_scene"]
