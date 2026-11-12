from __future__ import annotations

import http.client
import importlib
import importlib.util
import json
import sys
import tempfile
import threading
import time
import types
import unittest
from collections.abc import Callable
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

from scene.jobs import MeasurementJobManager
from scene.loader import Asset, BoundingBox, SceneRecord
from scene.web import AppState, HttpResponse, dispatch, make_handler

if TYPE_CHECKING:
    from scene.quicklook import QuicklookImage


def _stub_analyze_dependencies() -> None:
    if importlib.util.find_spec("numpy") is None:
        sys.modules.setdefault("numpy", types.ModuleType("numpy"))
    if importlib.util.find_spec("tifffile") is None:
        tifffile = types.ModuleType("tifffile")
        setattr(tifffile, "TiffFile", object)
        sys.modules.setdefault("tifffile", tifffile)
    if importlib.util.find_spec("PIL") is None:
        pil = types.ModuleType("PIL")
        pil_image = types.ModuleType("PIL.Image")
        pil_image_draw = types.ModuleType("PIL.ImageDraw")
        setattr(pil, "Image", pil_image)
        setattr(pil, "ImageDraw", pil_image_draw)
        setattr(pil, "UnidentifiedImageError", OSError)
        sys.modules.setdefault("PIL", pil)
        sys.modules.setdefault("PIL.Image", pil_image)
        sys.modules.setdefault("PIL.ImageDraw", pil_image_draw)
    if importlib.util.find_spec("scipy") is None:
        scipy = types.ModuleType("scipy")
        scipy_ndimage = types.ModuleType("scipy.ndimage")
        setattr(scipy, "ndimage", scipy_ndimage)
        sys.modules.setdefault("scipy", scipy)
        sys.modules.setdefault("scipy.ndimage", scipy_ndimage)


_stub_analyze_dependencies()
analyze: Any = importlib.import_module("scene.analyze")


EXPECTED_STEPS = (
    "Checking that the GRD is on disk.",
    "Checking that the dwell stack is on disk.",
    "Checking the sub-aperture image.",
    "Measuring dark water and the long bright return.",
    "Tracking bright returns across the dwell.",
    "Comparing each return with its sub-aperture neighborhood.",
    "Recording the SLC sidecar without detecting on it.",
    "Drawing the overview.",
    "Writing the measurement, the GeoJSON, and the briefing.",
)


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


def wait_for_status(
    manager: MeasurementJobManager, status: str, timeout: float = 2.0
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = manager.current().to_public()
        if payload["status"] == status:
            return payload
        time.sleep(0.01)
    return manager.current().to_public()


def write_result(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "measurements.json").write_text(
        json.dumps({"water_km2": 12.3, "returns": []}), encoding="utf-8"
    )
    (output_dir / "briefing.md").write_text("# Briefing\n\nMeasured.", encoding="utf-8")
    (output_dir / "overview.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")


class RunMeasurementTest(unittest.TestCase):
    def test_run_measurement_reports_the_nine_steps_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            output = root / "intelligence"
            data.mkdir()
            for name in ("grd-cog.tif", "vid-cog.tif", "csi-cog.tif"):
                (data / name).write_bytes(b"present")
            (data / "grd-json.json").write_text(
                json.dumps({"properties": {"proj:transform": [1, 0, 0, 0, -1, 0]}}),
                encoding="utf-8",
            )
            (data / "vid-json.json").write_text(
                json.dumps({"properties": {"proj:transform": [1, 0, 0, 0, -1, 0]}}),
                encoding="utf-8",
            )
            (data / "stac.json").write_text(
                json.dumps(
                    {
                        "properties": {
                            "start_datetime": "2025-01-01T00:00:00Z",
                            "end_datetime": "2025-01-01T00:00:15Z",
                        }
                    }
                ),
                encoding="utf-8",
            )
            steps: list[tuple[int, str]] = []
            scene: dict[str, object] = {
                "_mean": object(),
                "_water": object(),
                "_bridge": None,
                "_returns": [],
                "_grid": object(),
                "_scale": 1.0,
                "returns": [],
            }
            with (
                patch.object(analyze, "DATA", data),
                patch.object(analyze, "OUT", output),
                patch.object(analyze, "load_reduced", side_effect=[{}, {}]),
                patch.object(analyze, "measure_grd", return_value=scene),
                patch.object(analyze, "load_video", return_value=(object(), 1.0)),
                patch.object(analyze.Grid, "from_transform", return_value=object()),
                patch.object(analyze, "measure_motion"),
                patch.object(analyze, "measure_subaperture"),
                patch.object(analyze, "slc_note", return_value={"used": False}),
                patch.object(analyze, "save_overview"),
                patch.object(analyze, "write_products"),
                patch.object(analyze, "model_briefing", return_value=None),
                patch.object(analyze, "render_briefing", return_value="# Briefing\n"),
                patch("builtins.print"),
            ):
                analyze.run_measurement(
                    lambda index, sentence: steps.append((index, sentence))
                )
            self.assertEqual(steps, list(enumerate(EXPECTED_STEPS, start=1)))
            self.assertEqual(
                (output / "briefing.md").read_text(encoding="utf-8"), "# Briefing\n"
            )

    def test_run_measurement_fails_fast_when_required_raster_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            steps: list[tuple[int, str]] = []
            with patch.object(analyze, "DATA", data):
                with self.assertRaisesRegex(
                    RuntimeError, r"data/grd-cog\.tif.*python -m scene\.fetch --all"
                ):
                    analyze.run_measurement(
                        lambda index, sentence: steps.append((index, sentence))
                    )
            self.assertEqual(steps, [(1, EXPECTED_STEPS[0])])


class JobManagerTest(unittest.TestCase):
    def test_current_job_is_idle_before_start(self) -> None:
        manager = MeasurementJobManager(runner=lambda _on_step: None)
        payload = response_json(
            dispatch("GET", "/api/jobs/current", b"", make_state(), manager)
        )
        self.assertEqual(payload["status"], "idle")
        self.assertEqual(payload["step_index"], 0)
        self.assertEqual(payload["step_count"], 9)
        self.assertEqual(payload["sentence"], "")
        self.assertIsNone(payload["error"])
        self.assertIsNone(payload["result"])

    def test_job_lifecycle_running_done_and_409(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "intelligence"
            started = threading.Event()
            release = threading.Event()

            def runner(on_step: Callable[[int, str], None]) -> None:
                on_step(4, EXPECTED_STEPS[3])
                started.set()
                self.assertTrue(release.wait(timeout=2))
                on_step(9, EXPECTED_STEPS[8])
                write_result(output_dir)

            manager = MeasurementJobManager(runner=runner, output_dir=output_dir)
            state = make_state()
            accepted = dispatch("POST", "/api/jobs/measure", b"", state, manager)
            self.assertEqual(accepted.status, 202)
            first = response_json(accepted)
            self.assertEqual(first["status"], "running")
            self.assertIsInstance(first["job_id"], str)
            self.assertTrue(started.wait(timeout=2))

            conflict = dispatch("POST", "/api/jobs/measure", b"", state, manager)
            self.assertEqual(conflict.status, 409)
            running = response_json(
                dispatch("GET", "/api/jobs/current", b"", state, manager)
            )
            self.assertEqual(running["status"], "running")
            self.assertEqual(running["step_index"], 4)
            self.assertIsNone(running["result"])

            release.set()
            done = wait_for_status(manager, "done")
            self.assertEqual(done["status"], "done")
            self.assertEqual(done["step_count"], 9)
            result = cast(dict[str, object], done["result"])
            self.assertEqual(result["overview_url"], "/overview.png")
            self.assertIn("<h1>Briefing</h1>", cast(str, result["briefing_html"]))

    def test_job_failure_keeps_error_as_sentence(self) -> None:
        def runner(on_step: Callable[[int, str], None]) -> None:
            on_step(1, EXPECTED_STEPS[0])
            raise RuntimeError(
                "Missing data/vid-cog.tif. Run python -m scene.fetch --all."
            )

        manager = MeasurementJobManager(runner=runner, output_dir=Path("unused"))
        job_id = manager.start()
        self.assertTrue(job_id)
        failed = wait_for_status(manager, "failed")
        self.assertEqual(failed["status"], "failed")
        self.assertIn("data/vid-cog.tif", cast(str, failed["sentence"]))
        self.assertIn("python -m scene.fetch --all", cast(str, failed["error"]))
        self.assertIsNone(failed["result"])


class WebApiTest(unittest.TestCase):
    def test_scene_json_uses_state_and_existing_intelligence_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "intelligence"
            write_result(output_dir)
            manager = MeasurementJobManager(
                runner=lambda _on_step: None, output_dir=output_dir
            )
            quicklook = cast(
                "QuicklookImage",
                SimpleNamespace(png=b"\x89PNG\r\n\x1a\nfake", width=10, height=9),
            )
            payload = response_json(
                dispatch("GET", "/api/scene", b"", make_state(quicklook), manager)
            )
            self.assertEqual(payload["scene_id"], "scene-1")
            self.assertEqual(payload["look"], "right")
            self.assertEqual(payload["polarizations"], ["VV"])
            self.assertEqual(payload["bbox"], [-9.2, 38.6, -9.1, 38.7])
            self.assertEqual(payload["preview_url"], "/quicklook.png")
            self.assertEqual(payload["overview_url"], "/overview.png")
            self.assertEqual(
                cast(dict[str, object], payload["measurement"])["water_km2"], 12.3
            )
            self.assertIn("<p>Measured.</p>", cast(str, payload["briefing_html"]))

    def test_overview_png_is_served_only_from_intelligence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "intelligence"
            manager = MeasurementJobManager(
                runner=lambda _on_step: None, output_dir=output_dir
            )
            state = make_state()
            missing = dispatch("GET", "/overview.png", b"", state, manager)
            self.assertEqual(missing.status, 404)
            output_dir.mkdir()
            (output_dir / "overview.png").write_bytes(b"overview")
            found = dispatch("GET", "/overview.png", b"", state, manager)
            self.assertEqual(found.status, 200)
            self.assertEqual(found.body, b"overview")

    def test_root_falls_back_until_dist_index_exists_then_serves_index(self) -> None:
        state = make_state()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = MeasurementJobManager(runner=lambda _on_step: None)
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
            manager = MeasurementJobManager(runner=lambda _on_step: None)
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

    def test_empty_measure_post_without_content_length_returns_202(self) -> None:
        finished = threading.Event()

        def runner(on_step: Callable[[int, str], None]) -> None:
            on_step(1, EXPECTED_STEPS[0])
            finished.set()

        manager = MeasurementJobManager(runner=runner)
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(make_state(), manager)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.putrequest("POST", "/api/jobs/measure")
            conn.endheaders()
            response = conn.getresponse()
            self.assertEqual(response.status, 202)
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["status"], "running")
            conn.close()
            self.assertTrue(finished.wait(timeout=2))
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


class LisbonWordingTest(unittest.TestCase):
    def test_the_long_return_is_not_named_a_bridge_or_a_ship(self) -> None:
        import numpy as np

        from scene.grid import Grid

        maximum = np.full((50, 30), 10.0, dtype=np.float32)
        water = np.zeros(maximum.shape, dtype=bool)
        water[:, :6] = True
        maximum[:, 6:9] = 100.0
        found = analyze.find_bridge(
            maximum,
            water,
            10.0,
            10.0,
            10.0,
            10.0,
            Grid(0.0, 0.001, 0.0, 0.0, 0.0, -0.001),
            1.0,
        )
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found["kind"], "long bright return")
        self.assertNotIn("ship", str(found["kind"]))
        self.assertNotIn("bridge", str(found["kind"]))

        briefing = analyze.render_briefing(
            {
                "water_km2": 1.0,
                "scene_km2": 2.0,
                "water_fraction": 0.5,
                "water_sigma0_db": -16.0,
                "measurement_grid_m": 8,
                "dwell_s": 15,
                "basins": [{"area_km2": 0.4, "median_sigma0_db": -17.0}],
                "bridge": {"length_m": 500, "width_m": 40, "peak_sigma0_db": 12.0},
                "returns": [
                    {
                        "lat": 38.69,
                        "lon": -9.17,
                        "motion": "moved",
                        "displacement_m": 30,
                        "speed_m_s": 2,
                        "area_m2": 80,
                        "peak_sigma0_db": 8,
                    }
                ],
            }
        )
        self.assertIn("Water component 1", briefing)
        self.assertIn("long bright return", briefing)
        self.assertIn("not a named ship", briefing)
        self.assertNotIn("bridge", briefing.lower())
        self.assertNotIn("deck", briefing.lower())


if __name__ == "__main__":
    unittest.main()
