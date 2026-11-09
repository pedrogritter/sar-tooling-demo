"""The server answers the page, the PNG, and a browser error, and nothing else."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from lisbon_scene.web import AppState, build_state, dispatch, make_handler

SCENE_ID = "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF"


class DispatchTest(unittest.TestCase):
    state: AppState

    @classmethod
    def setUpClass(cls) -> None:
        cls.state = build_state()

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
        with self.assertLogs("lisbon_scene", level="ERROR") as logs:
            response = dispatch(
                "POST",
                "/client-error",
                json.dumps({"message": "boom", "source": "scene.js"}).encode("utf-8"),
                self.state,
            )
        self.assertEqual(response.status, 204)
        self.assertTrue(any("boom" in line for line in logs.output))


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
