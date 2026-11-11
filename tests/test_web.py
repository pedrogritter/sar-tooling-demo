"""The server answers the page, the PNG, and a browser error, and nothing else."""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from scene.jobs import MeasurementJobManager
from scene.web import AppState, build_state, dispatch, make_handler
from tests.test_belt import OpenWaterPictureTest, _rooted

SCENE_ID = "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF"


class DispatchTest(unittest.TestCase):
    state: AppState
    _catalog_dir: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.state = build_state()
        cls._catalog_dir = Path(tempfile.mkdtemp(prefix="catalog-web-"))

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._catalog_dir, ignore_errors=True)

    def test_page_and_quicklook(self) -> None:
        page = dispatch("GET", "/", b"", self.state)
        self.assertEqual(page.status, 200)
        body = page.body.decode("utf-8")
        self.assertTrue(SCENE_ID in body or '<div id="root"></div>' in body)
        image = dispatch("GET", "/quicklook.png", b"", self.state)
        self.assertEqual(image.status, 200)
        self.assertTrue(image.body.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_unknown_path_is_not_the_data_directory(self) -> None:
        missing = dispatch("GET", "/data/stac.json", b"", self.state)
        self.assertEqual(missing.status, 404)

    def test_client_error_is_logged(self) -> None:
        with self.assertLogs("scene", level="ERROR") as logs:
            response = dispatch(
                "POST",
                "/client-error",
                json.dumps({"message": "boom", "source": "scene.js"}).encode("utf-8"),
                self.state,
            )
        self.assertEqual(response.status, 204)
        self.assertTrue(any("boom" in line for line in logs.output))

    def test_scene_routes_do_not_serve_the_data_directory(self) -> None:
        missing = dispatch("GET", "/api/scenes/not-a-real-scene", b"", self.state)
        self.assertEqual(missing.status, 404)
        escaped = dispatch("GET", "/api/scenes/../quicklook.png", b"", self.state)
        self.assertEqual(escaped.status, 404)
        raw = dispatch(
            "GET",
            "/data/scenes/ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF/stac.json",
            b"",
            self.state,
        )
        self.assertEqual(raw.status, 404)

    def test_catalog_search_and_bad_bbox(self) -> None:
        from tests.test_catalog import _service

        catalog = _service(self._catalog_dir)
        found = dispatch(
            "GET",
            "/api/catalog/search?q=6Q31WW&limit=5",
            b"",
            self.state,
            catalog=catalog,
        )
        self.assertEqual(found.status, 200)
        payload = json.loads(found.body.decode("utf-8"))
        self.assertEqual(payload["items"][0]["scene_id"].endswith("SLEDF"), True)
        self.assertIn("indexing", payload)
        bad = dispatch(
            "GET",
            "/api/catalog/search?bbox=nope",
            b"",
            self.state,
            catalog=catalog,
        )
        self.assertEqual(bad.status, 400)
        for query in ("bbox=nan,0,1,2", "bbox=1,1,0,2"):
            with self.subTest(query=query):
                rejected = dispatch(
                    "GET",
                    f"/api/catalog/search?{query}",
                    b"",
                    self.state,
                    catalog=catalog,
                )
                self.assertEqual(rejected.status, 400)


class AnalysisRouteTest(unittest.TestCase):
    def test_unknown_locked_and_missing_partner_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            writer = OpenWaterPictureTest()
            first = "ICEYE_A_20260211T000000Z_1_X1_SM"
            second = "ICEYE_B_20260212T000000Z_1_X1_SM"
            scan = "ICEYE_C_20260211T000000Z_1_X1_SC"
            writer._write_scene(root, first, dark=True)
            writer._write_scene(root, second, dark=False)
            writer._write_scene(root, scan, dark=True, mode="scan")
            rooted = _rooted(root)
            with (
                patch("scene.web.scene_dir", rooted),
                patch("scene.belt.catalog.scene_dir", rooted),
            ):
                unknown = self._post(first, "not-a-tool")
                self.assertEqual(unknown.status, 400)
                self.assertIn(b"Unknown tool", unknown.body)

                locked = self._post(scan, "open-water")
                self.assertEqual(locked.status, 400)
                self.assertIn(b"not radiometrically calibrated", locked.body)

                missing = self._post(first, "amplitude-change")
                self.assertEqual(missing.status, 400)
                self.assertIn(b"Choose a second scene", missing.body)

                stranger = self._post(first, "amplitude-change", partner_id=scan)
                self.assertEqual(stranger.status, 400)
                self.assertIn(b"Choose a second scene", stranger.body)

    def test_second_analysis_is_refused_while_one_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scene_id = "ICEYE_A_20260211T000000Z_1_X1_SM"
            OpenWaterPictureTest()._write_scene(root, scene_id, dark=True)
            rooted = _rooted(root)
            manager = MeasurementJobManager()
            started = threading.Event()
            release = threading.Event()

            def block(*_args: object, **_kwargs: object) -> None:
                started.set()
                self.assertTrue(release.wait(timeout=3))

            try:
                with (
                    patch("scene.web.scene_dir", rooted),
                    patch("scene.belt.catalog.scene_dir", rooted),
                    patch("scene.belt.run.run_tool", block),
                ):
                    first = self._post(scene_id, "open-water", manager)
                    self.assertEqual(first.status, 202)
                    self.assertTrue(started.wait(timeout=2))
                    second = self._post(scene_id, "open-water", manager)
                    self.assertEqual(second.status, 409)
            finally:
                release.set()
                thread = manager._thread
                if thread is not None:
                    thread.join(timeout=3)

    def test_analysis_png_does_not_follow_a_link_out_of_the_scene(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scene_id = "ICEYE_A_20260211T000000Z_1_X1_SM"
            OpenWaterPictureTest()._write_scene(root, scene_id, dark=True)
            folder = root / "scenes" / scene_id / "analysis" / "open-water"
            folder.mkdir(parents=True)
            overview = folder / "overview.png"
            overview.write_bytes(b"inside-png")
            outside = root / "secret.png"
            outside.write_bytes(b"secret-bytes")
            rooted = _rooted(root)
            url = f"/api/scenes/{scene_id}/analysis/open-water/overview.png"
            with (
                patch("scene.web.scene_dir", rooted),
                patch("scene.belt.catalog.scene_dir", rooted),
            ):
                served = dispatch("GET", url, b"", build_state())
                self.assertEqual(served.status, 200)
                self.assertEqual(served.body, b"inside-png")
                overview.unlink()
                overview.symlink_to(outside)
                escaped = dispatch("GET", url, b"", build_state())
            self.assertEqual(escaped.status, 404)
            self.assertNotIn(b"secret-bytes", escaped.body)

    def _post(
        self,
        scene_id: str,
        tool_id: str,
        manager: MeasurementJobManager | None = None,
        partner_id: str | None = None,
    ):
        payload: dict[str, str] = {"scene_id": scene_id, "tool_id": tool_id}
        if partner_id is not None:
            payload["partner_id"] = partner_id
        return dispatch(
            "POST",
            "/api/jobs/run",
            json.dumps(payload).encode("utf-8"),
            build_state(),
            job_manager=manager,
        )


class ServerTest(unittest.TestCase):
    def test_live_request_returns_the_bridge_page(self) -> None:
        state = build_state()
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            url = f"http://127.0.0.1:{port}/"
            with urllib.request.urlopen(url, timeout=5) as response:
                body = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
            self.assertIn("25 de Abril", body)
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/static/scene.css", timeout=5
            ) as response:
                self.assertIn(b"scene__limit", response.read())
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/missing", timeout=5)
            self.assertEqual(caught.exception.code, 404)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
