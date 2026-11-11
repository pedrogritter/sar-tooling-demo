"""Download jobs report byte counts from the file on disk."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import cast

from scene.catalog import CatalogService
from scene.downloads import DownloadAlreadyRunningError, DownloadError, DownloadManager
from tests.test_catalog import LISBON, _service


class DownloadJobTest(unittest.TestCase):
    def test_progress_conflict_and_failed_file_keeps_earlier_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            catalog = _service(root / "index")
            holder: dict[str, DownloadManager] = {}

            def fetch_file(href: str, target: Path) -> str:
                target.write_bytes(b"abcde")
                manager = holder["manager"]
                snapshot = manager.current()
                files = cast(list[dict[str, object]], snapshot["files"])
                active = [item for item in files if item["name"] == target.name]
                self.assertEqual(active[0]["state"], "downloading")
                self.assertEqual(active[0]["bytes_done"], 5)
                if target.name.endswith(".tif"):
                    raise OSError("disk full")
                return "done"

            manager = DownloadManager(
                catalog,
                fetch_file=fetch_file,
                remote_size=lambda _href: 5,
                scenes_root=root / "scenes",
            )
            holder["manager"] = manager
            with self.assertRaises(DownloadError):
                manager.start(LISBON, ["missing-key"])

            job_id = manager.start(LISBON, ["graphic", "slc-cog"])
            manager.wait()
            done = manager.current()
            self.assertEqual(done["status"], "failed")
            self.assertEqual(done["job_id"], job_id)
            files = cast(list[dict[str, object]], done["files"])
            by_name = {str(item["name"]): item for item in files}
            self.assertEqual(by_name["stac.json"]["state"], "done")
            self.assertEqual(by_name["graphic.png"]["state"], "done")
            self.assertEqual(by_name["slc-cog.tif"]["state"], "failed")
            folder = root / "scenes" / LISBON
            self.assertTrue((folder / "stac.json").is_file())
            self.assertEqual((folder / "graphic.png").read_bytes(), b"abcde")

    def test_second_start_is_refused_while_running(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            catalog = _service(Path(raw))
            started = threading.Event()
            release = threading.Event()

            def fetch_file(_href: str, target: Path) -> str:
                started.set()
                self.assertTrue(release.wait(timeout=2))
                target.write_bytes(b"abcde")
                return "kept"

            manager = DownloadManager(
                catalog,
                fetch_file=fetch_file,
                remote_size=lambda _href: 5,
                scenes_root=Path(raw) / "scenes",
            )
            manager.start(LISBON, ["graphic"])
            self.assertTrue(started.wait(timeout=2))
            with self.assertRaises(DownloadAlreadyRunningError):
                manager.start(LISBON, ["graphic"])
            release.set()
            manager.wait()
            self.assertEqual(manager.current()["status"], "done")
            graphic = next(
                item
                for item in cast(list[dict[str, object]], manager.current()["files"])
                if item["name"] == "graphic.png"
            )
            self.assertEqual(graphic["state"], "kept")

    def test_omitted_asset_list_downloads_the_preview_pack_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manager = DownloadManager(
                _service(root / "index"),
                fetch_file=_write_five,
                remote_size=lambda _href: 5,
                scenes_root=root / "scenes",
            )
            manager.start(LISBON, None)
            manager.wait()
            done = manager.current()
            self.assertEqual(done["status"], "done")
            names = {
                str(item["name"])
                for item in cast(list[dict[str, object]], done["files"])
            }
            self.assertEqual(names, {"stac.json", "graphic.png"})

    def test_asset_key_cannot_leave_the_scene_folder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            catalog = _service(
                root / "index",
                extra_assets={
                    "../escape": {
                        "href": "https://iceye-open-data-catalog.s3.amazonaws.com/data/x/escape.bin",
                        "title": "Escape",
                        "type": "application/octet-stream",
                    }
                },
            )
            manager = DownloadManager(
                catalog,
                fetch_file=_write_five,
                remote_size=lambda _href: 5,
                scenes_root=root / "scenes",
            )
            with self.assertRaises(DownloadError):
                manager.start(LISBON, ["../escape"])
            self.assertFalse((root / "escape.bin").exists())
            self.assertEqual(manager.current()["status"], "idle")

    def test_failed_download_leaves_the_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            folder = root / "scenes" / LISBON
            analysis = folder / "analysis" / "open-water"
            analysis.mkdir(parents=True)
            (folder / "demo.json").write_text(
                json.dumps({"placeholder": True, "note": "Demo placeholder."}),
                encoding="utf-8",
            )
            (analysis / "overview.png").write_bytes(b"png")
            (folder / "qlk-cog.tif").write_bytes(b"tif")

            def boom(_href: str, _target: Path) -> str:
                raise OSError("network down")

            manager = DownloadManager(
                _service(root / "index"),
                fetch_file=boom,
                remote_size=lambda _href: 5,
                scenes_root=root / "scenes",
            )
            manager.start(LISBON, ["graphic"])
            manager.wait()
            self.assertEqual(manager.current()["status"], "failed")
            self.assertTrue((folder / "demo.json").is_file())
            self.assertTrue((analysis / "overview.png").is_file())
            self.assertEqual((folder / "qlk-cog.tif").read_bytes(), b"tif")
            self.assertFalse((root / ".seed-applied").exists())

    def test_successful_download_strips_the_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            folder = root / "scenes" / LISBON
            analysis = folder / "analysis" / "open-water"
            analysis.mkdir(parents=True)
            (folder / "demo.json").write_text(
                json.dumps(
                    {"placeholder": True, "note": "Demo placeholder."}
                ),
                encoding="utf-8",
            )
            (analysis / "overview.png").write_bytes(b"png")
            (folder / "qlk-cog.tif").write_bytes(b"tif")
            manager = DownloadManager(
                _service(root / "index"),
                fetch_file=_write_five,
                remote_size=lambda _href: 5,
                scenes_root=root / "scenes",
            )
            manager.start(LISBON, ["graphic"])
            manager.wait()
            self.assertEqual(manager.current()["status"], "done")
            self.assertFalse((folder / "demo.json").exists())
            self.assertFalse(analysis.exists())
            self.assertFalse((folder / "qlk-cog.tif").exists())
            self.assertEqual((folder / "graphic.png").read_bytes(), b"abcde")
            self.assertEqual(
                (root / ".seed-applied").read_text(encoding="utf-8").strip(),
                "replaced",
            )


def _write_five(_href: str, target: Path) -> str:
    target.write_bytes(b"abcde")
    return "done"


class CatalogTypeGuard(unittest.TestCase):
    def test_service_fixture_is_a_catalog(self) -> None:
        self.assertIsInstance(_service(Path(".")), CatalogService)


if __name__ == "__main__":
    unittest.main()
