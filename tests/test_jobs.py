from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from scene.jobs import MeasurementJobManager
from scene.loader import Asset, BoundingBox, SceneRecord
from scene.web import AppState, HttpResponse, dispatch

if TYPE_CHECKING:
    from scene.quicklook import QuicklookImage


def make_state(quicklook: QuicklookImage | None = None) -> AppState:
    scene = SceneRecord(
        scene_id="scene-1",
        collected_at="2025-10-24T13:53:09Z",
        start_at="2025-10-24T13:53:01Z",
        end_at="2025-10-24T13:53:16Z",
        platform="ICEYE-X52",
        mode="spotlight",
        band="X",
        polarizations=("VV",),
        orbit_state="descending",
        look="right",
        incidence_angle=32.5,
        bbox=BoundingBox(west=-9.2, south=38.6, east=-9.1, north=38.7),
        assets=(
            Asset(
                key="qlk-cog",
                title="Quicklook",
                media_type="image/tiff",
                href="qlk-cog.tif",
                local_path=None,
            ),
        ),
    )
    return AppState(
        scene=scene,
        note_markdown="## Scene note\n\nCurrent paper page.",
        quicklook=quicklook,
        static_files={
            "/static/scene.css": ("text/css; charset=utf-8", b".scene{}"),
            "/static/scene.js": ("text/javascript; charset=utf-8", b""),
        },
    )


def response_json(response: HttpResponse) -> dict[str, object]:
    payload = json.loads(response.body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError("response body is not a JSON object")
    return cast(dict[str, object], payload)


class JobManagerTest(unittest.TestCase):
    def test_current_job_is_idle_before_start(self) -> None:
        manager = MeasurementJobManager()
        payload = response_json(
            dispatch("GET", "/api/jobs/current", b"", make_state(), manager)
        )
        self.assertEqual(payload["status"], "idle")
        self.assertEqual(payload["step_index"], 0)
        self.assertEqual(payload["step_count"], 9)
        self.assertEqual(payload["sentence"], "")
        self.assertIsNone(payload["error"])
        self.assertIsNone(payload["result"])


class WebApiTest(unittest.TestCase):
    def test_root_falls_back_until_dist_index_exists_then_serves_index(self) -> None:
        state = make_state()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = MeasurementJobManager()
            with patch("scene.web.project_root", return_value=root):
                fallback = dispatch("GET", "/", b"", state, manager)
                self.assertEqual(fallback.status, 200)
                self.assertIn("Current paper page", fallback.body.decode("utf-8"))

                dist = root / "frontend" / "dist"
                dist.mkdir(parents=True)
                (dist / "index.html").write_text("<main>React shell</main>")
                index = dispatch("GET", "/", b"", state, manager)
                self.assertEqual(index.status, 200)
                self.assertEqual(index.body, b"<main>React shell</main>")
                self.assertEqual(index.cache_control, "no-store")

    def test_dist_asset_cache_and_path_traversal(self) -> None:
        state = make_state()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = root / "frontend" / "dist" / "assets" / "index-abcd1234.js"
            asset.parent.mkdir(parents=True)
            asset.write_text("console.log('ok');", encoding="utf-8")
            (root / "frontend" / "dist" / "secret.txt").write_text(
                "secret", encoding="utf-8"
            )
            manager = MeasurementJobManager()
            with patch("scene.web.project_root", return_value=root):
                response = dispatch(
                    "GET", "/assets/index-abcd1234.js", b"", state, manager
                )
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    response.cache_control, "public, max-age=31536000, immutable"
                )
                blocked = dispatch("GET", "/assets/../secret.txt", b"", state, manager)
                self.assertEqual(blocked.status, 404)


if __name__ == "__main__":
    unittest.main()
