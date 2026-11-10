"""Serve the scene page.

From the repository root, after ``python -m scene.fetch``:

    python -m scene.serve

Then open http://127.0.0.1:8765
The process reads the STAC record, the scene note, and the quicklook.
It does not call a model.
"""

from __future__ import annotations

import logging
import os
import sys

from scene.loader import SceneDataError
from scene.web import build_state, serve


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    host = os.environ.get("SCENE_HOST", "127.0.0.1")
    port = _port(os.environ.get("SCENE_PORT", "8765"))
    try:
        state = build_state()
        serve(state, host=host, port=port)
    except SceneDataError as exc:
        logging.error("%s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(0)


def _port(raw: str) -> int:
    try:
        port = int(raw)
    except ValueError:
        logging.error("SCENE_PORT must be an integer, got %r", raw)
        sys.exit(1)
    if not 1 <= port <= 65535:
        logging.error("SCENE_PORT must be between 1 and 65535, got %s", port)
        sys.exit(1)
    return port


if __name__ == "__main__":
    main()
