"""The placeholder seed is copied once, and a real scene is not deleted."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scene.belt.catalog import tools_for_scene
from scene.demo import (
    PlaceholderMissing,
    SeedRasterError,
    clear_placeholder,
    note_from_folder,
    seed_if_needed,
    write_seed,
)
from scene.library import list_library
from scene.loader import load_scene
from scene.paths import LISBON_SCENE_ID
from scene.quicklook import render_quicklook_png
from scene.web import build_state, dispatch
from tests.test_belt import _rooted


class DemoSeedTest(unittest.TestCase):
    def test_seed_once_clear_keeps_stac_and_other_scenes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            seed = root / "seed"
            data = root / "data"
            write_seed(seed)
            self.assertTrue(seed_if_needed(data, seed))
            folder = data / "scenes" / LISBON_SCENE_ID
            stac = (folder / "stac.json").read_text(encoding="utf-8")
            (folder / "stac.json").write_text(stac + "\n", encoding="utf-8")
            self.assertFalse(seed_if_needed(data, seed))
            self.assertEqual(
                (folder / "stac.json").read_text(encoding="utf-8"),
                stac + "\n",
            )
            self.assertTrue((folder / "qlk-cog.tif").is_file())
            self.assertTrue(
                (folder / "analysis" / "open-water" / "measurements.json").is_file()
            )

            other = data / "scenes" / "OTHER_SCENE"
            other.mkdir()
            (other / "keep.txt").write_text("keep", encoding="utf-8")
            note = clear_placeholder(data)
            self.assertIn("Demo placeholder", note)
            self.assertTrue((folder / "stac.json").is_file())
            self.assertFalse((folder / "demo.json").exists())
            self.assertFalse((folder / "analysis").exists())
            self.assertFalse((folder / "qlk-cog.tif").exists())
            self.assertFalse((folder / "graphic.png").exists())
            self.assertEqual((other / "keep.txt").read_text(encoding="utf-8"), "keep")
            self.assertEqual(
                (data / ".seed-applied").read_text(encoding="utf-8").strip(),
                "cleared",
            )
            self.assertFalse(seed_if_needed(data, seed))
            (folder / "stac.json").unlink()
            self.assertTrue(seed_if_needed(data, seed))
            self.assertTrue((folder / "stac.json").is_file())
            self.assertTrue((folder / "demo.json").is_file())
            self.assertTrue((folder / "qlk-cog.tif").is_file())
            with self.assertRaises(PlaceholderMissing):
                clear_placeholder(root / "data-absent")

    def test_existing_stac_and_marker_are_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            data = root / "data"
            folder = data / "scenes" / LISBON_SCENE_ID
            folder.mkdir(parents=True)
            (folder / "stac.json").write_text("real", encoding="utf-8")
            self.assertFalse(seed_if_needed(data, root / "missing-seed"))
            self.assertEqual(
                (folder / "stac.json").read_text(encoding="utf-8"),
                "real",
            )
            self.assertFalse((folder / "demo.json").exists())

            seed = root / "seed"
            write_seed(seed)
            occupied = root / "occupied"
            scene = occupied / "scenes" / LISBON_SCENE_ID
            scene.mkdir(parents=True)
            (scene / "grd-cog.tif").write_bytes(b"REAL-GRD")
            (scene / "qlk-cog.tif").write_bytes(b"REAL-QLK")
            self.assertFalse(seed_if_needed(occupied, seed))
            self.assertEqual((scene / "qlk-cog.tif").read_bytes(), b"REAL-QLK")
            self.assertEqual((scene / "grd-cog.tif").read_bytes(), b"REAL-GRD")
            self.assertFalse((scene / "demo.json").exists())
            self.assertFalse((scene / "stac.json").exists())

            empty = root / "empty"
            empty.mkdir()
            (empty / ".seed-applied").write_text("cleared\n", encoding="utf-8")
            self.assertTrue(seed_if_needed(empty, seed))
            restored = empty / "scenes" / LISBON_SCENE_ID / "stac.json"
            self.assertTrue(restored.is_file())

    def test_saved_tool_and_quicklook(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            write_seed(dest)
            folder = dest / "scenes" / LISBON_SCENE_ID
            scene = load_scene(folder / "stac.json")
            self.assertEqual(scene.scene_id, LISBON_SCENE_ID)
            self.assertEqual(scene.collected_at, "2025-10-24T13:53:16.995Z")
            self.assertEqual(scene.start_at, "2025-10-24T13:53:09.803Z")
            self.assertEqual(scene.end_at, "2025-10-24T13:53:24.188Z")
            self.assertAlmostEqual(scene.bbox.west, -9.213969443201776)
            self.assertAlmostEqual(scene.bbox.north, 38.71784777157828)
            quicklook = scene.asset("qlk-cog")
            self.assertIsNotNone(quicklook)
            assert quicklook is not None
            self.assertTrue(quicklook.on_disk)
            image = render_quicklook_png(folder / "qlk-cog.tif")
            self.assertTrue(image.png.startswith(b"\x89PNG\r\n\x1a\n"))

            listed = list_library(dest)
            self.assertTrue(listed[0]["placeholder"])
            with patch("scene.belt.catalog.scene_dir", _rooted(dest)):
                views = {item.id: item for item in tools_for_scene(LISBON_SCENE_ID)}
            water = views["open-water"]
            self.assertTrue(water.locked)
            self.assertIn("Demo placeholder", water.reason)
            self.assertIn("grd-cog.tif", water.reason)
            measurement = water.measurement
            self.assertIsInstance(measurement, dict)
            assert isinstance(measurement, dict)
            summary = measurement["summary"]
            self.assertIsInstance(summary, list)
            assert isinstance(summary, list)
            self.assertIn("placeholder", summary[0]["value"])
            self.assertIsNotNone(water.briefing_html)
            assert water.briefing_html is not None
            self.assertIn("Demo placeholder", water.briefing_html)
            self.assertIsNone(views["dwell-motion"].measurement)
            self.assertIsNone(views["dwell-motion"].overview_url)

    def test_clear_route_removes_only_the_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            data = Path(raw)
            write_seed(data)
            state = build_state()
            with patch("scene.demo.data_dir", lambda: data):
                rejected = dispatch(
                    "POST",
                    "/api/demo/clear",
                    b"{}",
                    state,
                )
                self.assertEqual(rejected.status, 400)
                cleared = dispatch("POST", "/api/demo/clear", b"", state)
            self.assertEqual(cleared.status, 200)
            payload = json.loads(cleared.body.decode("utf-8"))
            self.assertTrue(payload["cleared"])
            self.assertIn("Demo placeholder", payload["note"])
            folder = data / "scenes" / LISBON_SCENE_ID
            self.assertTrue((folder / "stac.json").is_file())
            self.assertFalse((folder / "demo.json").exists())
            with patch("scene.demo.data_dir", lambda: data):
                missing = dispatch("POST", "/api/demo/clear", b"", state)
            self.assertEqual(missing.status, 404)

    def test_missing_lisbon_tree_still_draws_the_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            dest = root / "seed"
            write_seed(dest, root / "absent")
            folder = dest / "scenes" / LISBON_SCENE_ID
            self.assertTrue((folder / "demo.json").is_file())
            self.assertTrue((folder / "qlk-cog.tif").is_file())
            self.assertFalse((folder / "preview.png").exists())
            self.assertIsNotNone(note_from_folder(folder))

    def test_committed_lisbon_seed_copies_preview_without_a_raster(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "lisbon"
            scene = source / "scenes" / LISBON_SCENE_ID
            scene.mkdir(parents=True)
            (scene / "stac.json").write_text(
                json.dumps(_collect(LISBON_SCENE_ID)), encoding="utf-8"
            )
            (scene / "preview.png").write_bytes(b"preview-bytes")
            (scene / "graphic.png").write_bytes(b"graphic-bytes")
            (scene / "vid-mp4.mp4").write_bytes(b"video-bytes")
            (scene / "demo.json").write_text(
                '{"placeholder": true}\n', encoding="utf-8"
            )
            dest = root / "seed"
            write_seed(dest, source)
            copied = dest / "scenes" / LISBON_SCENE_ID
            self.assertEqual((copied / "preview.png").read_bytes(), b"preview-bytes")
            self.assertEqual((copied / "graphic.png").read_bytes(), b"graphic-bytes")
            self.assertEqual((copied / "vid-mp4.mp4").read_bytes(), b"video-bytes")
            self.assertFalse((copied / "demo.json").exists())
            self.assertIsNone(note_from_folder(copied))
            self.assertFalse(any(path.suffix == ".tif" for path in copied.rglob("*")))
            listed = list_library(dest)
            self.assertEqual(
                listed[0]["quicklook_url"],
                f"/api/scenes/{LISBON_SCENE_ID}/quicklook.png",
            )

    def test_committed_seed_rejects_a_radar_raster(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "lisbon"
            scene = source / "scenes" / LISBON_SCENE_ID
            scene.mkdir(parents=True)
            (scene / "stac.json").write_text("{}\n", encoding="utf-8")
            (scene / "preview.png").write_bytes(b"preview")
            (scene / "qlk-cog.tif").write_bytes(b"not-a-real-raster")
            dest = root / "seed"
            with self.assertRaises(SeedRasterError) as caught:
                write_seed(dest, source)
            self.assertIn("qlk-cog.tif", str(caught.exception))
            self.assertFalse(dest.exists())

    def test_preview_png_alone_is_a_quicklook_url(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            folder = root / "scenes" / LISBON_SCENE_ID
            folder.mkdir(parents=True)
            (folder / "stac.json").write_text(
                json.dumps(_collect(LISBON_SCENE_ID)), encoding="utf-8"
            )
            (folder / "preview.png").write_bytes(b"preview-bytes")
            listed = list_library(root)
            self.assertEqual(
                listed[0]["quicklook_url"],
                f"/api/scenes/{LISBON_SCENE_ID}/quicklook.png",
            )
            self.assertIsNone(listed[0]["thumbnail_url"])
            self.assertFalse(listed[0]["placeholder"])


def _collect(scene_id: str) -> dict[str, object]:
    """A few dozen bytes of metadata. Not a downloaded scene."""

    return {
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
        "assets": {
            "graphic": {
                "href": "https://example.invalid/graphic.png",
                "type": "image/png",
                "title": "Thumbnail",
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
