"""Loader tests. The real Lisbon item is checked, and broken files fail fast."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scene.loader import SceneDataError, load_scene

SCENE_ID = "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF"


class RealSceneTest(unittest.TestCase):
    def test_lisbon_collect_and_local_assets(self) -> None:
        scene = load_scene()
        self.assertEqual(scene.scene_id, SCENE_ID)
        self.assertEqual(scene.platform, "ICEYE-X52")
        self.assertEqual(scene.mode, "spotlight")
        self.assertEqual(scene.band, "X")
        self.assertEqual(scene.polarizations, ("VV",))
        self.assertEqual(scene.orbit_state, "descending")
        self.assertAlmostEqual(scene.incidence_angle, 32.035387, places=3)
        self.assertLess(scene.bbox.west, -9.2)
        self.assertGreater(scene.bbox.north, 38.7)

        quicklook = scene.asset("qlk-cog")
        self.assertIsNotNone(quicklook)
        assert quicklook is not None
        self.assertIsNotNone(quicklook.local_path)
        assert quicklook.local_path is not None
        self.assertEqual(quicklook.local_path.name, "qlk-cog.tif")

        slc = scene.asset("slc-cog")
        self.assertIsNotNone(slc)
        assert slc is not None
        self.assertTrue(slc.href.startswith("https://"))
        slc_file = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "scenes"
            / SCENE_ID
            / "slc-cog.tif"
        )
        if slc_file.is_file():
            self.assertEqual(slc.local_path, slc_file)
        else:
            self.assertIsNone(slc.local_path)


class FixtureSceneTest(unittest.TestCase):
    def test_local_file_is_paired_by_scene_py_name(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "graphic.png").write_bytes(b"png")
            item = _item()
            path = root / "stac.json"
            path.write_text(json.dumps(item), encoding="utf-8")
            scene = load_scene(path)
            graphic = scene.asset("graphic")
            self.assertIsNotNone(graphic)
            assert graphic is not None
            self.assertEqual(graphic.local_path, root / "graphic.png")
            # The STAC key is kept. The file is absent, so there is no local path.
            quicklook = scene.asset("qlk-cog")
            self.assertIsNotNone(quicklook)
            assert quicklook is not None
            self.assertIsNone(quicklook.local_path)
            self.assertEqual(quicklook.href, "https://example.test/quicklook.tif")

    def test_missing_file_names_scene_py(self) -> None:
        with self.assertRaises(SceneDataError) as caught:
            load_scene(Path("/tmp/does-not-exist-lisbon-stac.json"))
        self.assertIn("python -m scene.fetch", str(caught.exception))

    def test_bad_bbox_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "stac.json"
            item = _item()
            item["bbox"] = [1, 2, 3]
            path.write_text(json.dumps(item), encoding="utf-8")
            with self.assertRaises(SceneDataError):
                load_scene(path)


def _item() -> dict[str, object]:
    return {
        "id": SCENE_ID,
        "bbox": [-9.214, 38.660, -9.140, 38.718],
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
                "href": "https://example.test/thumb.png",
                "type": "image/png",
                "title": "Thumbnail",
            },
            "qlk-cog": {
                "href": "https://example.test/quicklook.tif",
                "type": "image/tiff",
                "title": "Quicklook",
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
