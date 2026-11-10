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

from scene.web import AppState, build_state, dispatch, make_handler

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
