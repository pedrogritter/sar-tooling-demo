"""The library is a scan of scene folders, with the Lisbon id marked."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scene.library import list_library
from scene.paths import LISBON_SCENE_ID


class LibraryScanTest(unittest.TestCase):
    def test_lists_ready_scenes_and_skips_a_broken_folder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            lisbon = root / "scenes" / LISBON_SCENE_ID
            other = root / "scenes" / "ICEYE_6Q31WW_20251110T182058Z_7010715_X56_SLEDF"
            broken = root / "scenes" / "not-a-scene"
            lisbon.mkdir(parents=True)
            other.mkdir(parents=True)
            broken.mkdir(parents=True)
            (lisbon / "stac.json").write_text(
                json.dumps(_item(LISBON_SCENE_ID, "2025-10-24T13:53:16Z")),
                encoding="utf-8",
            )
            (lisbon / "graphic.png").write_bytes(b"png")
            (other / "stac.json").write_text(
                json.dumps(
                    _item(
                        "ICEYE_6Q31WW_20251110T182058Z_7010715_X56_SLEDF",
                        "2025-11-10T18:21:11Z",
                    )
                ),
                encoding="utf-8",
            )
            (broken / "stac.json").write_text("{", encoding="utf-8")

            scenes = list_library(root)

        self.assertEqual(
            [scene["scene_id"] for scene in scenes],
            [
                LISBON_SCENE_ID,
                "ICEYE_6Q31WW_20251110T182058Z_7010715_X56_SLEDF",
            ],
        )
        self.assertTrue(scenes[0]["is_test_scene"])
        self.assertEqual(scenes[0]["assets_on_disk"], ["graphic"])
        self.assertIsNotNone(scenes[0]["thumbnail_url"])
        self.assertFalse(scenes[1]["is_test_scene"])


def _item(scene_id: str, collected: str) -> dict[str, object]:
    return {
        "id": scene_id,
        "bbox": [-9.214, 38.660, -9.140, 38.718],
        "properties": {
            "datetime": collected,
            "start_datetime": collected,
            "end_datetime": collected,
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
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
