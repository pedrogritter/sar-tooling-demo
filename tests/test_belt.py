"""Belt measurements on synthetic scenes, and the lock sentences."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import numpy as np
import tifffile

from scene.belt.catalog import tools_for_scene
from scene.belt.measure import change_masks, split_roughness, water_mask
from scene.belt.run import run_tool
from scene.belt.stack import dark_anomaly, persistence


class WaterAndChangeTest(unittest.TestCase):
    def test_dark_half_is_water_and_a_flat_sea_stays_one_class(self) -> None:
        db = np.full((40, 60), -5.0, dtype=np.float32)
        db[:, :30] = -18.0
        water, _mode = water_mask(db)
        self.assertGreater(int(water[:, :30].sum()), int(water[:, 30:].sum()))
        calm, rough, note = split_roughness(
            np.full((20, 20), -16.0), np.ones((20, 20), dtype=bool)
        )
        self.assertFalse(calm.any())
        self.assertTrue(rough.any())
        self.assertIn("one class", note)

    def test_change_under_one_and_a_half_db_stays_gray(self) -> None:
        earlier = np.zeros((8, 8), dtype=np.float32)
        later = earlier.copy()
        later[:, 4:] = 3.0
        later[:, :2] = -3.0
        darker, brighter = change_masks(earlier, later)
        self.assertTrue(darker[:, :2].all())
        self.assertTrue(brighter[:, 4:].all())
        self.assertFalse(darker[:, 2:4].any())
        self.assertFalse(brighter[:, 2:4].any())

    def test_anomaly_is_darker_than_the_stack_median(self) -> None:
        frame = np.full((30, 30), -12.0, dtype=np.float32)
        frame[10:18, 10:18] = -20.0
        median = np.full((30, 30), -12.0, dtype=np.float32)
        water = np.ones((30, 30), dtype=bool)
        anomaly = dark_anomaly(frame, median, water)
        self.assertTrue(anomaly[12, 12])
        self.assertFalse(anomaly[2, 2])
        fraction = persistence(
            [np.ones((4, 4), dtype=bool), np.zeros((4, 4), dtype=bool)]
        )
        self.assertAlmostEqual(float(fraction[0, 0]), 0.5)


class OpenWaterPictureTest(unittest.TestCase):
    def test_a_scene_folder_draws_a_legend(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scene_id = "ICEYE_TEST_20260211T000000Z_1_X1_SM"
            self._write_scene(root, scene_id, dark=True)
            with (
                patch("scene.belt.catalog.scene_dir", _rooted(root)),
                patch("scene.belt.run.scene_dir", _rooted(root)),
            ):
                run_tool(scene_id, "open-water", lambda _index, _sentence: None)
            overview = (
                root / "scenes" / scene_id / "analysis" / "open-water" / "overview.png"
            )
            self.assertTrue(overview.is_file())
            measurement = json.loads(
                (overview.parent / "measurements.json").read_text(encoding="utf-8")
            )
            self.assertEqual(measurement["tool_id"], "open-water")
            self.assertTrue(measurement["summary"])

    def test_scan_stays_locked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scene_id = "ICEYE_TEST_20260211T000000Z_1_X1_SC"
            self._write_scene(root, scene_id, dark=True, mode="scan")
            with patch("scene.belt.catalog.scene_dir", _rooted(root)):
                views = {item.id: item for item in tools_for_scene(scene_id)}
            self.assertTrue(views["open-water"].locked)
            self.assertIn("not radiometrically calibrated", views["open-water"].reason)

    def _write_scene(
        self, root: Path, scene_id: str, dark: bool, mode: str = "stripmap"
    ) -> None:
        folder = root / "scenes" / scene_id
        folder.mkdir(parents=True)
        values = np.full((32, 48), 40, dtype=np.float32)
        if dark:
            values[:, :24] = 8
        tifffile.imwrite(folder / "grd-cog.tif", values)
        transform = [-16.8, 0.001, 0.0, 28.1, 0.0, -0.001]
        (folder / "grd-json.json").write_text(
            json.dumps(
                {
                    "properties": {
                        "proj:transform": transform,
                        "iceye:calibration_factor": 1e-4,
                    }
                }
            ),
            encoding="utf-8",
        )
        (folder / "stac.json").write_text(
            json.dumps(
                {
                    "id": scene_id,
                    "bbox": [-16.9, 28.0, -16.6, 28.3],
                    "properties": {
                        "datetime": "2026-02-11T00:00:00Z",
                        "start_datetime": "2026-02-11T00:00:00Z",
                        "end_datetime": "2026-02-11T00:00:10Z",
                        "platform": "ICEYE-X1",
                        "sar:instrument_mode": mode,
                        "sar:frequency_band": "X",
                        "sar:polarizations": ["VV"],
                        "sat:orbit_state": "ascending",
                        "sar:observation_direction": "right",
                        "view:incidence_angle": 26.0,
                    },
                    "assets": {
                        "grd-cog": {
                            "href": "https://example.test/grd.tif",
                            "type": "image/tiff",
                        },
                        "grd-json": {
                            "href": "https://example.test/grd.json",
                            "type": "application/json",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )


def _rooted(root: Path) -> Callable[[str], Path]:
    def scene_directory(scene_id: str) -> Path:
        if not scene_id:
            raise ValueError("invalid")
        return root / "scenes" / scene_id

    return scene_directory


class PairLockTest(unittest.TestCase):
    def test_two_tenerife_like_strips_can_pair(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = "ICEYE_A_20260211T000000Z_1_X1_SM"
            second = "ICEYE_B_20260212T000000Z_1_X1_SM"
            writer = OpenWaterPictureTest()
            writer._write_scene(root, first, dark=True)
            writer._write_scene(root, second, dark=False)
            stac = root / "scenes" / second / "stac.json"
            payload = json.loads(stac.read_text(encoding="utf-8"))
            payload["properties"]["datetime"] = "2026-02-12T00:00:00Z"
            stac.write_text(json.dumps(payload), encoding="utf-8")
            with patch("scene.belt.catalog.scene_dir", _rooted(root)):
                views = {item.id: item for item in tools_for_scene(first)}
            self.assertFalse(views["amplitude-change"].locked)
            self.assertIn(second, views["amplitude-change"].partners)
            self.assertTrue(views["stack-mean"].locked)
            self.assertTrue(views["dwell-motion"].locked)
            self.assertIn("vid-cog.tif", views["dwell-motion"].reason)
            with (
                patch("scene.belt.catalog.scene_dir", _rooted(root)),
                patch("scene.belt.run.scene_dir", _rooted(root)),
            ):
                run_tool(
                    first,
                    "amplitude-change",
                    lambda _index, _sentence: None,
                    second,
                )
                run_tool(
                    first,
                    "water-persistence",
                    lambda _index, _sentence: None,
                )
                run_tool(
                    first,
                    "dark-sea-anomaly",
                    lambda _index, _sentence: None,
                )
            change = (
                root
                / "scenes"
                / first
                / "analysis"
                / "amplitude-change"
                / second
                / "overview.png"
            )
            persistence = (
                root
                / "scenes"
                / first
                / "analysis"
                / "water-persistence"
                / "overview.png"
            )
            anomaly = (
                root
                / "scenes"
                / first
                / "analysis"
                / "dark-sea-anomaly"
                / "overview.png"
            )
            self.assertTrue(change.is_file())
            self.assertTrue(persistence.is_file())
            self.assertTrue(anomaly.is_file())


if __name__ == "__main__":
    unittest.main()
