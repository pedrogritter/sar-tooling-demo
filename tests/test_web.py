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
from typing import Any
from unittest.mock import patch

from PIL import Image

from scene.jobs import MeasurementJobManager
from scene.web import AppState, HttpResponse, build_state, dispatch, make_handler
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
    ) -> HttpResponse:
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


class PreviewVideoRouteTest(unittest.TestCase):
    """The quicklook and the video control, using a few dozen fixture bytes."""

    state: AppState

    @classmethod
    def setUpClass(cls) -> None:
        cls.state = build_state()

    def test_quicklook_returns_preview_png_when_the_cog_is_absent(self) -> None:
        preview = b"preview-bytes-unchanged"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scene_id = "ICEYE_PREVIEW_20251024T135309Z_1_X52_SLF"
            _write_collect(
                root,
                scene_id,
                {"graphic": _asset("https://example.invalid/graphic.png", "image/png")},
                {"preview.png": preview},
            )
            with patch("scene.web.scene_dir", _rooted(root)):
                response = dispatch(
                    "GET",
                    f"/api/scenes/{scene_id}/quicklook.png",
                    b"",
                    self.state,
                )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "image/png")
        self.assertEqual(response.body, preview)

    def test_quicklook_cog_still_wins_over_preview_png(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scene_id = "ICEYE_PREVIEW_20251024T135309Z_1_X52_SLF"
            folder = _write_collect(
                root,
                scene_id,
                {
                    "qlk-cog": _asset(
                        "https://example.invalid/qlk-cog.tif", "image/tiff"
                    )
                },
                {"preview.png": b"preview-not-this"},
            )
            Image.new("L", (4, 4), color=90).save(folder / "qlk-cog.tif", format="TIFF")
            with patch("scene.web.scene_dir", _rooted(root)):
                response = dispatch(
                    "GET",
                    f"/api/scenes/{scene_id}/quicklook.png",
                    b"",
                    self.state,
                )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "image/png")
        self.assertTrue(response.body.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertNotEqual(response.body, b"preview-not-this")

    def test_video_route_returns_the_mp4_not_the_dwell_stack(self) -> None:
        mp4 = b"mp4-fixture-bytes-0123456789-ABCDEFG"
        cog = b"vid-cog-must-not-be-served-0000"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scene_id = "ICEYE_VIDEO_20251024T135309Z_1_X52_SLF"
            _write_collect(
                root,
                scene_id,
                {
                    "vid-mp4": _asset(
                        "https://example.invalid/vid-mp4.mp4", "video/mp4"
                    ),
                    "vid-cog": _asset(
                        "https://example.invalid/vid-cog.tif", "image/tiff"
                    ),
                },
                {"vid-mp4.mp4": mp4, "vid-cog.tif": cog},
            )
            with (
                patch("scene.web.scene_dir", _rooted(root)),
                _refuse_dwell_stack(),
            ):
                response = dispatch(
                    "GET", f"/api/scenes/{scene_id}/video", b"", self.state
                )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "video/mp4")
        self.assertEqual(response.body, mp4)
        self.assertIn(("Accept-Ranges", "bytes"), response.headers)
        self.assertNotIn(cog, response.body)

    def test_video_route_honors_a_byte_range(self) -> None:
        mp4 = b"mp4-fixture-bytes-0123456789-ABCDEFG"
        cog = b"vid-cog-must-not-be-served-0000"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scene_id = "ICEYE_VIDEO_20251024T135309Z_1_X52_SLF"
            _write_collect(
                root,
                scene_id,
                {
                    "vid-mp4": _asset(
                        "https://example.invalid/vid-mp4.mp4", "video/mp4"
                    ),
                    "vid-cog": _asset(
                        "https://example.invalid/vid-cog.tif", "image/tiff"
                    ),
                },
                {"vid-mp4.mp4": mp4, "vid-cog.tif": cog},
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.state))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/api/scenes/{scene_id}/video"
            try:
                with (
                    patch("scene.web.scene_dir", _rooted(root)),
                    _refuse_dwell_stack(),
                ):
                    request = urllib.request.Request(
                        url, headers={"Range": "bytes=0-3"}
                    )
                    with urllib.request.urlopen(request, timeout=5) as response:
                        body = response.read()
                        status = response.status
                        content_range = response.headers["Content-Range"]
                        accept = response.headers["Accept-Ranges"]
                        content_type = response.headers["Content-Type"]
                    head = urllib.request.Request(
                        url, headers={"Range": "bytes=0-3"}, method="HEAD"
                    )
                    with urllib.request.urlopen(head, timeout=5) as response:
                        head_status = response.status
                        head_range = response.headers["Content-Range"]
                        head_length = response.headers["Content-Length"]
                        head_body = response.read()
                    past = urllib.request.Request(
                        url, headers={"Range": f"bytes={len(mp4)}-{len(mp4) + 3}"}
                    )
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(past, timeout=5)
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()
        self.assertEqual(status, 206)
        self.assertEqual(body, mp4[:4])
        self.assertEqual(content_type, "video/mp4")
        self.assertEqual(content_range, f"bytes 0-3/{len(mp4)}")
        self.assertEqual(accept, "bytes")
        self.assertNotIn(cog, body)
        self.assertEqual(head_status, 206)
        self.assertEqual(head_range, f"bytes 0-3/{len(mp4)}")
        self.assertEqual(head_length, "4")
        self.assertEqual(head_body, b"")
        self.assertEqual(caught.exception.code, 416)
        self.assertEqual(
            caught.exception.headers["Content-Range"], f"bytes */{len(mp4)}"
        )


def _write_collect(
    root: Path,
    scene_id: str,
    assets: dict[str, dict[str, str]],
    files: dict[str, bytes],
) -> Path:
    folder = root / "scenes" / scene_id
    folder.mkdir(parents=True)
    payload = {
        "id": scene_id,
        "bbox": [-9.214, 38.66, -9.14, 38.718],
        "properties": {
            "datetime": "2025-10-24T13:53:16.995Z",
            "start_datetime": "2025-10-24T13:53:09.803Z",
            "end_datetime": "2025-10-24T13:53:24.188Z",
            "platform": "ICEYE-X52",
            "sar:instrument_mode": "spotlight",
            "sar:frequency_band": "X",
            "sar:polarizations": ["VV"],
            "sat:orbit_state": "descending",
            "view:incidence_angle": 32.0,
        },
        "assets": assets,
    }
    (folder / "stac.json").write_text(json.dumps(payload), encoding="utf-8")
    for name, payload_bytes in files.items():
        (folder / name).write_bytes(payload_bytes)
    return folder


def _asset(href: str, media_type: str) -> dict[str, str]:
    return {"href": href, "type": media_type, "title": href.rsplit("/", 1)[-1]}


class _RefuseDwellStack:
    """Fails the test when the video route opens ``vid-cog.tif``."""

    def __init__(self) -> None:
        self._patch: Any = None

    def __enter__(self) -> None:
        original = Path.open

        def guard(self: Path, *args: Any, **kwargs: Any) -> Any:
            if self.name == "vid-cog.tif":
                raise AssertionError("video route opened vid-cog.tif")
            return original(self, *args, **kwargs)

        self._patch = patch.object(Path, "open", guard)
        self._patch.start()

    def __exit__(self, *_exc: object) -> None:
        self._patch.stop()


def _refuse_dwell_stack() -> _RefuseDwellStack:
    return _RefuseDwellStack()


if __name__ == "__main__":
    unittest.main()
