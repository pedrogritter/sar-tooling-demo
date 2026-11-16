"""Toolkit measurements on synthetic scenes, and the lock sentences."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import numpy as np
import tifffile

from scene.grid import Grid, metres
from scene.paths import LISBON_SCENE_ID, scene_dir
from scene.toolkit.catalog import TOOLS, ToolView, tools_for_scene
from scene.toolkit.geometry import INCIDENCE_TOLERANCE, warp_affine
from scene.toolkit.measure import (
    TOOL_CONTROLS,
    Control,
    ControlError,
    _axis_lengths,
    built_up_mask,
    catalog_defaults,
    change_masks,
    long_structure,
    parse_control_overrides,
    resolve_controls,
    split_roughness,
    suggested_value,
    track_returns,
    water_mask,
    waterline_returns,
)
from scene.toolkit.run import (
    LIMITS,
    Frame,
    _load_frame,
    _single_layers,
    limit_for,
    run_tool,
)
from scene.toolkit.stack import (
    dark_anomaly,
    date_of_change,
    persistence,
    repeat_counts,
    sea_state,
    shoreline,
    site_activity,
)


class WaterAndChangeTest(unittest.TestCase):
    def test_dark_half_is_water_and_a_flat_sea_stays_one_class(self) -> None:
        db = np.full((40, 60), -5.0, dtype=np.float32)
        db[:, :30] = -18.0
        water, _mode = water_mask(db)
        self.assertGreater(int(water[:, :30].sum()), int(water[:, 30:].sum()))
        calm, rough, note = split_roughness(
            np.full((20, 20), -16.0), np.ones((20, 20), dtype=bool)
        )
        self.assertTrue(calm.any())
        self.assertFalse(rough.any())
        self.assertIn("one class", note)

    def test_an_enclosed_island_stays_dry(self) -> None:
        rng = np.random.default_rng(2)
        db = np.full((100, 100), -16.0, dtype=np.float32)
        db += rng.normal(0, 0.04, db.shape).astype(np.float32)
        island = -6.0 + rng.normal(0, 0.04, (40, 40)).astype(np.float32)
        db[30:70, 30:70] = island
        water, mode = water_mask(db)
        self.assertLess(mode, -12.0)
        self.assertLess(float(water[40:60, 40:60].mean()), 0.1)
        self.assertGreater(float(water[5:15, 5:15].mean()), 0.8)
        self.assertLess(float(water.mean()), 0.9)

    def test_low_contrast_textured_land_is_not_the_whole_scene(self) -> None:
        rng = np.random.default_rng(1)
        db = np.full((160, 160), 13.0, dtype=np.float32)
        db += rng.normal(0, 0.015, db.shape).astype(np.float32)
        db[50:120, 50:120] += rng.normal(0.05, 0.12, (70, 70)).astype(np.float32)
        water, _mode = water_mask(db)
        self.assertLess(float(water.mean()), 0.9)
        self.assertLess(float(water[70:100, 70:100].mean()), 0.35)
        self.assertGreater(float(water[5:25, 5:25].mean()), 0.7)

    def test_change_under_three_db_or_a_small_patch_is_excluded(self) -> None:
        earlier = np.zeros((8, 8), dtype=np.float32)
        later = earlier.copy()
        later[:, 4:] = 3.0
        later[:, :2] = -3.0
        darker, brighter = change_masks(earlier, later)
        self.assertTrue(darker[:, :2].all())
        self.assertTrue(brighter[:, 4:].all())
        self.assertFalse(darker[:, 2:4].any())
        self.assertFalse(brighter[:, 2:4].any())

        speckled = np.zeros((12, 12), dtype=np.float32)
        later_speckle = speckled.copy()
        later_speckle[0, 0] = 10.0
        later_speckle[2:8, 2:8] = 2.0
        faint_dark, faint_bright = change_masks(speckled, later_speckle)
        self.assertFalse(faint_dark.any())
        self.assertFalse(faint_bright.any())

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
                patch("scene.toolkit.catalog.scene_dir", _rooted(root)),
                patch("scene.toolkit.run.scene_dir", _rooted(root)),
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
            with patch("scene.toolkit.catalog.scene_dir", _rooted(root)):
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
            with patch("scene.toolkit.catalog.scene_dir", _rooted(root)):
                views = {item.id: item for item in tools_for_scene(first)}
            self.assertFalse(views["amplitude-change"].locked)
            self.assertIn(second, views["amplitude-change"].partners)
            self.assertTrue(views["stack-mean"].locked)
            self.assertTrue(views["dwell-motion"].locked)
            self.assertIn("vid-cog.tif", views["dwell-motion"].reason)
            with (
                patch("scene.toolkit.catalog.scene_dir", _rooted(root)),
                patch("scene.toolkit.run.scene_dir", _rooted(root)),
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


class StackToolTest(unittest.TestCase):
    def test_a_uniformly_dark_sea_is_not_an_anomaly_and_the_shore_is_the_edge(
        self,
    ) -> None:
        frame = np.full((20, 20), -20.0, dtype=np.float32)
        median = np.full((20, 20), -12.0, dtype=np.float32)
        water = np.ones((20, 20), dtype=bool)
        self.assertFalse(dark_anomaly(frame, median, water).any())

        mask = np.zeros((8, 8), dtype=bool)
        mask[2:6, 2:6] = True
        edge = shoreline(mask)
        self.assertTrue(edge[2, 2])
        self.assertFalse(edge[3, 3])
        self.assertFalse(edge[0, 0])

        levels = sea_state(
            [np.full((4, 4), -15.0, dtype=np.float32), np.zeros((4, 4))],
            [np.ones((4, 4), dtype=bool), np.zeros((4, 4), dtype=bool)],
        )
        self.assertEqual(levels[0], -15.0)
        self.assertIsNone(levels[1])

    def test_date_of_change_ignores_a_speck_and_keeps_a_four_db_patch(self) -> None:
        frames = [np.zeros((12, 12), dtype=np.float32) for _ in range(3)]
        frames[1] = frames[1].copy()
        frames[1][0, 0] = 10.0
        frames[2] = frames[2].copy()
        frames[2][2:8, 2:8] = 4.0
        which, keep = date_of_change(frames)
        self.assertFalse(keep[0, 0])
        self.assertEqual(int(which[0, 0]), -1)
        self.assertTrue(keep[4, 4])
        self.assertEqual(int(which[4, 4]), 2)

    def test_site_activity_names_a_new_cluster_and_not_a_single_pixel(self) -> None:
        frame = np.full((12, 12), -20.0, dtype=np.float32)
        median = frame.copy()
        frame[2:6, 2:6] = -8.0
        frame[0, 11] = -8.0
        appeared, left = site_activity(frame, median, -18.0)
        self.assertTrue(appeared[3, 3])
        self.assertFalse(appeared[0, 11])
        self.assertFalse(left.any())


class SingleSceneTest(unittest.TestCase):
    def test_land_majority_keeps_the_dark_peak_and_a_flat_field_does_not_split(
        self,
    ) -> None:
        db = np.full((40, 40), -5.0, dtype=np.float32)
        db[:16, :16] = -18.0
        water, mode = water_mask(db)
        self.assertLess(mode, -12.0)
        self.assertGreater(int(water[:16, :16].sum()), int(water[16:, 16:].sum()))

        split = np.full((20, 20), -10.0, dtype=np.float32)
        split[:, :10] = -20.0
        calm, rough, note = split_roughness(split, np.ones((20, 20), dtype=bool))
        self.assertTrue(calm[:, :10].all())
        self.assertTrue(rough[:, 10:].all())
        self.assertIn("median", note)
        self.assertNotIn("wave", note.lower())

    def test_close_half_medians_stay_one_class(self) -> None:
        # Spread is 5 dB, so the 1.5 dB shortcut does not fire. The median
        # cut leaves halves at -17.4 dB and -16.5 dB, about 0.9 dB apart.
        values = np.concatenate(
            [
                np.full(200, -20.0),
                np.full(300, -17.4),
                np.full(300, -16.5),
                np.full(200, -15.0),
            ]
        ).astype(np.float32)
        db = values.reshape(20, 50)
        water = np.ones(db.shape, dtype=bool)
        calm, rough, note = split_roughness(db, water)
        self.assertTrue(np.array_equal(calm, water))
        self.assertFalse(rough.any())
        self.assertEqual(
            note,
            "The two classes differ by less than 1.5 dB, "
            "so the water is drawn as one class.",
        )

    def test_a_hull_is_not_built_up_and_a_dim_land_pixel_is_not_either(self) -> None:
        water = np.zeros((40, 40), dtype=bool)
        water[:, :10] = True
        db = np.full((40, 40), -14.0, dtype=np.float32)
        db[water] = 0.0
        db[5:12, 20:28] = -8.0
        built = built_up_mask(db, water, -18.0)
        self.assertTrue(built[8, 24])
        self.assertFalse(built[5, 5])
        self.assertFalse(built[0, 30])

    def test_a_bright_return_must_touch_the_water_and_a_short_one_is_not_long(
        self,
    ) -> None:
        # 48 rows leaves an end-to-end axis over 200 m after closing trims the border.
        db = np.full((48, 80), -16.0, dtype=np.float32)
        water = np.zeros(db.shape, dtype=bool)
        water[:, :6] = True
        db[water] = -18.0
        db[8:12, 6:10] = -2.0
        db[8:12, 60:64] = -2.0
        found = waterline_returns(db, water, -18.0, 5.0, 5.0)
        self.assertEqual(len(found), 1)
        self.assertLess(found[0].col, 20)

        db[:, 6:9] = -2.0
        structure = long_structure(db, water, -18.0, 5.0, 5.0)
        self.assertIsNotNone(structure)
        assert structure is not None
        self.assertGreater(structure.length_m, 200)

        short = np.full((40, 80), -16.0, dtype=np.float32)
        short_water = np.zeros(short.shape, dtype=bool)
        short_water[:, :6] = True
        short[10:14, 6:10] = -2.0
        self.assertIsNone(long_structure(short, short_water, -18.0, 5.0, 5.0))

    def test_a_return_eighty_metres_inland_does_not_count(self) -> None:
        pixel_m = 10.0
        db = np.full((30, 30), -16.0, dtype=np.float32)
        water = np.zeros(db.shape, dtype=bool)
        water[:, :1] = True
        db[2:6, 1:5] = -2.0
        db[20:24, 8:12] = -2.0
        found = waterline_returns(db, water, -18.0, pixel_m, pixel_m)
        self.assertEqual(len(found), 1)
        self.assertLess(found[0].col, 5.0)

        near = np.zeros(db.shape, dtype=bool)
        near[2:6, 1:5] = True
        blocked = waterline_returns(db, water, -18.0, pixel_m, pixel_m, near)
        self.assertEqual(blocked, [])

    def test_a_dwell_track_is_motion_during_the_stare_not_a_route(self) -> None:
        moving = np.zeros((5, 20, 20), dtype=np.float32)
        for index in range(5):
            moving[index, 8, 4 + index] = 100
        moved = track_returns(moving, [(8.0, 4.0)], 1.0, 1.0, 10.0, 10.0)
        self.assertEqual(moved[0]["motion"], "moved")
        moved_m = moved[0]["displacement_m"]
        self.assertIsInstance(moved_m, float)
        assert isinstance(moved_m, float)
        self.assertGreater(moved_m, 20)
        self.assertNotIn("route", str(moved[0]["motion"]))

        still = np.zeros((5, 20, 20), dtype=np.float32)
        still[:, 8, 4] = 100
        stayed = track_returns(still, [(8.0, 4.0)], 1.0, 1.0, 10.0, 10.0)
        self.assertEqual(stayed[0]["motion"], "stationary during the dwell")

        # The ridge is brighter at the original centre than along the line,
        # and a hotter peak steps one column per frame. A window that
        # recentered would follow that peak. The fixed window does not.
        ridge = np.zeros((12, 16, 40), dtype=np.float32)
        ridge[:, 8, :] = 30.0
        ridge[:, 8, 8] = 60.0
        for index in range(12):
            ridge[index, 8, 8 + index] = 100.0
        crawled = track_returns(ridge, [(8.0, 8.0)], 1.0, 1.0, 5.0, 12.0)
        self.assertEqual(crawled[0]["motion"], "stationary during the dwell")
        displacement = crawled[0]["displacement_m"]
        self.assertIsInstance(displacement, float)
        assert isinstance(displacement, float)
        self.assertLess(displacement, 20.0)

    def test_open_water_record_keeps_the_shadow_limit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scene_id = "ICEYE_TEST_20260211T000000Z_1_X1_SM"
            OpenWaterPictureTest()._write_scene(root, scene_id, dark=True)
            with (
                patch("scene.toolkit.catalog.scene_dir", _rooted(root)),
                patch("scene.toolkit.run.scene_dir", _rooted(root)),
            ):
                run_tool(scene_id, "open-water", lambda _index, _sentence: None)
                run_tool(scene_id, "sea-roughness", lambda _index, _sentence: None)
            water = json.loads(
                (
                    root
                    / "scenes"
                    / scene_id
                    / "analysis"
                    / "open-water"
                    / "measurements.json"
                ).read_text(encoding="utf-8")
            )
            rough = json.loads(
                (
                    root
                    / "scenes"
                    / scene_id
                    / "analysis"
                    / "sea-roughness"
                    / "measurements.json"
                ).read_text(encoding="utf-8")
            )
        self.assertIn("Shadow", water["limit"])
        self.assertNotIn("ship", water["limit"].lower())
        self.assertIn("not a wave", rough["limit"])
        labels = {row["label"]: row["value"] for row in rough["summary"]}
        self.assertEqual(labels["Split"], "none")


class EligibilityTest(unittest.TestCase):
    def test_scan_and_scan_wide_stay_locked(self) -> None:
        for mode in ("scan", "scan_wide"):
            with self.subTest(mode=mode):
                reason = self._open_water_reason(mode=mode)
                self.assertIn("not radiometrically calibrated", reason)

    def test_missing_calibration_factor_stays_locked(self) -> None:
        reason = self._open_water_reason(drop_factor=True)
        self.assertIn("no calibration factor", reason)

    def test_pair_refuses_a_different_look_a_wide_incidence_and_a_small_overlap(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = "ICEYE_A_20260211T000000Z_1_X1_SM"
            second = "ICEYE_B_20260212T000000Z_1_X1_SM"
            writer = OpenWaterPictureTest()
            writer._write_scene(root, first, dark=True)
            writer._write_scene(root, second, dark=False)
            self._patch_stac(
                root,
                second,
                {"sar:observation_direction": "left"},
            )
            self.assertNotIn(second, self._partners(root, first))

            self._patch_stac(
                root,
                second,
                {
                    "sar:observation_direction": "right",
                    "view:incidence_angle": 26.0 + INCIDENCE_TOLERANCE + 0.2,
                },
            )
            views = self._views(root, first)
            self.assertNotIn(second, views["amplitude-change"].partners)
            reason = views["amplitude-change"].reason
            self.assertIn("within 1 degree", reason)
            self.assertIn("30 percent", reason)

            self._patch_stac(
                root,
                second,
                {"view:incidence_angle": 26.0 + INCIDENCE_TOLERANCE},
                bbox=[-16.7, 28.2, -16.4, 28.5],
            )
            self.assertNotIn(second, self._partners(root, first))

            self._patch_stac(
                root,
                second,
                {"view:incidence_angle": 26.0},
                bbox=[-16.9, 28.0, -16.6, 28.3],
            )
            self.assertIn(second, self._partners(root, first))

    def test_warp_lands_a_shifted_pixel_on_the_destination_grid(self) -> None:
        source = Grid(0.0, 0.001, 0.0, 0.0, 0.0, -0.001)
        destination = Grid(0.002, 0.001, 0.0, 0.0, 0.0, -0.001)
        values = np.zeros((4, 6), dtype=np.float32)
        values[0, 2] = 9.0
        warped = np.asarray(
            warp_affine(values, source, 1.0, (4, 6), destination, 1.0)
        )
        self.assertAlmostEqual(float(warped[0, 0]), 9.0, places=4)
        self.assertTrue(np.isnan(warped[0, 5]))

    def _open_water_reason(
        self, mode: str = "stripmap", drop_factor: bool = False
    ) -> str:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scene_id = "ICEYE_TEST_20260211T000000Z_1_X1_SM"
            OpenWaterPictureTest()._write_scene(root, scene_id, dark=True, mode=mode)
            if drop_factor:
                path = root / "scenes" / scene_id / "grd-json.json"
                payload = json.loads(path.read_text(encoding="utf-8"))
                del payload["properties"]["iceye:calibration_factor"]
                path.write_text(json.dumps(payload), encoding="utf-8")
            with patch("scene.toolkit.catalog.scene_dir", _rooted(root)):
                views = {item.id: item for item in tools_for_scene(scene_id)}
            view = views["open-water"]
            self.assertTrue(view.locked)
            return view.reason

    def _partners(self, root: Path, scene_id: str) -> tuple[str, ...]:
        return self._views(root, scene_id)["amplitude-change"].partners

    def _views(self, root: Path, scene_id: str) -> dict[str, ToolView]:
        with patch("scene.toolkit.catalog.scene_dir", _rooted(root)):
            return {item.id: item for item in tools_for_scene(scene_id)}

    def _patch_stac(
        self,
        root: Path,
        scene_id: str,
        properties: dict[str, object],
        bbox: list[float] | None = None,
    ) -> None:
        path = root / "scenes" / scene_id / "stac.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["properties"].update(properties)
        if bbox is not None:
            payload["bbox"] = bbox
        path.write_text(json.dumps(payload), encoding="utf-8")


class LongStructureAxisTest(unittest.TestCase):
    """End-to-end length, the diagonal stroke, and the corridor past the band."""

    def test_a_straight_bar_reports_its_end_to_end_length(self) -> None:
        # 61 centres at 10 m span 600 m. Four standard deviations is about 15% high.
        db = np.full((90, 40), -16.0, dtype=np.float32)
        water = np.zeros(db.shape, dtype=bool)
        water[:, :5] = True
        db[10:71, 8] = -2.0
        structure = long_structure(db, water, -18.0, 10.0, 10.0)
        self.assertIsNotNone(structure)
        assert structure is not None
        self.assertAlmostEqual(structure.length_m, 600.0, delta=30.0)

    def test_a_diagonal_stroke_follows_the_bar(self) -> None:
        db, water = _diagonal_bar()
        frame = Frame(
            "synthetic",
            "synthetic",
            db,
            Grid(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            1.0,
            4.0,
            4.0,
            -20.0,
            0.0,
        )
        summary, _layers, strokes, _legend = _single_layers(
            "long-structure", frame, water, -18.0
        )
        self.assertEqual(len(strokes), 1)
        self.assertEqual(len(strokes[0].points), 2)
        start, end = strokes[0].points
        self.assertGreater(abs(start[1] - end[1]), 20.0)
        reported = float(
            {row["label"]: row["value"] for row in summary}["Length"].split()[0]
        )
        ground = float(np.hypot((end[0] - start[0]) * 4.0, (end[1] - start[1]) * 4.0))
        self.assertAlmostEqual(ground, reported, delta=4.0)

    def test_a_diagonal_bar_exposes_ends(self) -> None:
        db, water = _diagonal_bar()
        structure = long_structure(db, water, -18.0, 4.0, 4.0)
        self.assertIsNotNone(structure)
        assert structure is not None
        self.assertIsNotNone(structure.ends)
        assert structure.ends is not None
        start, end = structure.ends
        self.assertGreater(abs(start[1] - end[1]), 20.0)

    def test_compact_returns_keep_the_covariance_ellipse(self) -> None:
        db = np.full((40, 80), -16.0, dtype=np.float32)
        water = np.zeros(db.shape, dtype=bool)
        water[:, :6] = True
        db[8:16, 6:14] = -2.0
        found = waterline_returns(db, water, -18.0, 5.0, 5.0)
        self.assertEqual(len(found), 1)
        rows, cols = np.nonzero(found[0].mask)
        length_m, _width_m = _axis_lengths(rows, cols, 5.0, 5.0)
        self.assertAlmostEqual(found[0].length_m, length_m)

    def test_corridor_follows_a_bright_continuation_past_the_band(self) -> None:
        # Shoreline piece is 530 m. The aligned run past 150 m adds 410 m.
        db, water = _shoreline_bar()
        db[32, 64:105] = -2.0
        structure = long_structure(db, water, -18.0, 10.0, 10.0)
        self.assertIsNotNone(structure)
        assert structure is not None
        self.assertAlmostEqual(structure.length_m, 940.0, delta=47.0)

    def test_corridor_skips_an_offset_blob(self) -> None:
        db, water = _shoreline_bar()
        db[40, 64:105] = -2.0
        structure = long_structure(db, water, -18.0, 10.0, 10.0)
        self.assertIsNotNone(structure)
        assert structure is not None
        self.assertGreater(structure.length_m, 450.0)
        self.assertLess(structure.length_m, 750.0)

    def test_corridor_stops_at_a_dark_gap(self) -> None:
        # Four dark pixels at 10 m is 40 m, longer than the 2-pixel closing gap.
        db, water = _shoreline_bar()
        db[32, 68:111] = -2.0
        structure = long_structure(db, water, -18.0, 10.0, 10.0)
        self.assertIsNotNone(structure)
        assert structure is not None
        self.assertGreater(structure.length_m, 450.0)
        self.assertLess(structure.length_m, 750.0)


# Stored deck line from intelligence/returns.geojson. South end, then north end.
_STORED_DECK = (
    (-9.174131929401266, 38.68104102292412),
    (-9.17888681141543, 38.70161252161052),
)
_LISBON_GRD = scene_dir(LISBON_SCENE_ID) / "grd-cog.tif"


class LisbonStructureTest(unittest.TestCase):
    @unittest.skipUnless(_LISBON_GRD.is_file(), "Lisbon GRD is not on disk")
    def test_the_deck_length_and_line_match_the_stored_return(self) -> None:
        frame = _load_frame(LISBON_SCENE_ID)
        water, mode = water_mask(frame.db)
        structure = long_structure(
            frame.db, water, mode, frame.col_m, frame.row_m
        )
        self.assertIsNotNone(structure)
        assert structure is not None
        assert structure.ends is not None
        self.assertGreaterEqual(structure.length_m, 2164.0)
        self.assertLessEqual(structure.length_m, 2392.0)
        self.assertGreater(structure.width_m, 80.0)

        start, end = structure.ends
        samples = _samples(start, end, 21)
        distances = [
            _segment_distance_m(
                frame.grid.to_lonlat(col, row, frame.scale),
                _STORED_DECK[0],
                _STORED_DECK[1],
            )
            for col, row in samples
        ]
        self.assertLessEqual(float(np.median(distances)), 40.0)
        self.assertLessEqual(max(distances), 80.0)

        start_ll = frame.grid.to_lonlat(start[0], start[1], frame.scale)
        end_ll = frame.grid.to_lonlat(end[0], end[1], frame.scale)
        ground = metres(*start_ll, *end_ll)
        pixel_m = max(frame.col_m, frame.row_m)
        self.assertAlmostEqual(ground, structure.length_m, delta=pixel_m)


def _samples(
    start: tuple[float, float], end: tuple[float, float], count: int
) -> list[tuple[float, float]]:
    cols = np.linspace(start[0], end[0], count)
    rows = np.linspace(start[1], end[1], count)
    return list(zip(cols.tolist(), rows.tolist(), strict=True))


def _segment_distance_m(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Distance from a lon/lat point to a short segment, in metres."""

    def frame(lon: float, lat: float) -> tuple[float, float]:
        east = (lon - point[0]) * 111_320 * math.cos(math.radians(point[1]))
        north = (lat - point[1]) * 110_540
        return east, north

    ax, ay = frame(*start)
    bx, by = frame(*end)
    abx, aby = bx - ax, by - ay
    denom = abx * abx + aby * aby
    if denom == 0:
        return math.hypot(ax, ay)
    share = max(0.0, min(1.0, (-ax * abx - ay * aby) / denom))
    return math.hypot(ax + abx * share, ay + aby * share)


def _diagonal_bar() -> tuple[np.ndarray, np.ndarray]:
    """A thick bar inside the 150 m band, clearly off a constant row."""

    db = np.full((120, 50), -16.0, dtype=np.float32)
    water = np.zeros(db.shape, dtype=bool)
    water[:, :8] = True
    rows = np.linspace(10, 100, 300)
    cols = np.linspace(12, 28, 300)
    for row, col in zip(rows, cols):
        r = int(round(float(row)))
        c = int(round(float(col)))
        db[r - 1 : r + 2, c - 1 : c + 2] = -2.0
    return db, water


def _shoreline_bar() -> tuple[np.ndarray, np.ndarray]:
    """A 530 m return along the water, ending where the shore leaves the 150 m band."""

    db = np.full((50, 160), -16.0, dtype=np.float32)
    water = np.zeros(db.shape, dtype=bool)
    water[10:30, 0:50] = True
    db[32, 10:64] = -2.0
    return db, water


def _control(tool_id: str, control_id: str) -> Control:
    for spec in TOOL_CONTROLS[tool_id]:
        if spec.id == control_id:
            return spec
    raise AssertionError(control_id)


def _synthetic_frame(db: np.ndarray, pixel_m: float = 5.0) -> Frame:
    return Frame(
        "synthetic",
        "2026-01-01T00:00:00Z",
        db,
        Grid(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        1.0,
        pixel_m,
        pixel_m,
        -20.0,
        0.0,
    )


def _labels(summary: list[dict[str, str]]) -> set[str]:
    return {row["label"] for row in summary}


class OpenWaterControlTest(unittest.TestCase):
    def test_defaults_keep_the_shadow_sentence_and_the_gates_move_the_mask(
        self,
    ) -> None:
        self.assertEqual(
            set(TOOL_CONTROLS),
            {spec.id for spec in TOOLS},
        )
        defaults = catalog_defaults("open-water")
        self.assertEqual(limit_for("open-water", defaults), LIMITS["open-water"])
        self.assertIn("Shadow, tarmac, and sand", LIMITS["open-water"])
        self.assertIn("marks them dry", LIMITS["open-water"])

        db = np.tile(np.linspace(-20, -8, 48, dtype=np.float32), (48, 1))
        tight, _mode = water_mask(db, water_gate_db=0.5)
        wide, _mode = water_mask(db, water_gate_db=4)
        self.assertGreater(int(wide.sum()), int(tight.sum()))

        rng = np.random.default_rng(1)
        flat = np.full((160, 160), 13.0, dtype=np.float32)
        flat += rng.normal(0, 0.015, flat.shape).astype(np.float32)
        flat[50:120, 50:120] += rng.normal(0.05, 0.12, (70, 70)).astype(np.float32)
        small = water_mask(flat, texture_window_px=5)[0]
        broad = water_mask(flat, texture_window_px=61)[0]
        self.assertFalse(np.array_equal(small, broad))

        holed = np.full((80, 80), -8.0, dtype=np.float32)
        holed[:, :50] = -18.0
        holed[20:26, 20:26] = -8.0
        filled = water_mask(holed, max_hole_px=256)[0]
        open_hole = water_mask(holed, max_hole_px=8)[0]
        self.assertTrue(bool(filled[22, 22]))
        self.assertFalse(bool(open_hole[22, 22]))

        summary, layers, strokes, legend = _single_layers(
            "open-water", _synthetic_frame(db), wide, -18.0, defaults
        )
        self.assertEqual(
            _labels(summary),
            {"Water area", "Water fraction", "Median sigma-nought"},
        )
        self.assertEqual(len(layers), 1)
        self.assertEqual(strokes, [])
        self.assertEqual(legend, ["Blue: open water."])
        self.assertEqual(
            limit_for("open-water", {"water_gate_db": 3, **defaults}),
            LIMITS["open-water"],
        )

    def test_incidence_and_pixel_suggestions_fill_omitted_keys(self) -> None:
        gate = _control("open-water", "water_gate_db")
        window = _control("open-water", "texture_window_px")
        self.assertEqual(suggested_value(gate, None, None), 1.5)
        self.assertEqual(suggested_value(gate, 26, None), 1.5)
        self.assertEqual(suggested_value(gate, 34, None), 1.5)
        self.assertEqual(suggested_value(gate, 30, None), 1.5)
        self.assertAlmostEqual(suggested_value(gate, 24, None), 2.5)
        self.assertAlmostEqual(suggested_value(gate, 36, None), 2.5)
        self.assertAlmostEqual(suggested_value(gate, 20, None), 4.0)
        self.assertEqual(suggested_value(window, None, None), 31)
        self.assertEqual(suggested_value(window, None, 1), 31)
        self.assertEqual(suggested_value(window, None, 2), 15)
        # 3.1 pixels is under the control minimum, so the suggestion stops at 5.
        self.assertEqual(suggested_value(window, None, 10), 5)
        self.assertEqual(suggested_value(window, None, 0.1), 61)
        suggested = resolve_controls("open-water", None, 40.0, 2.0)
        self.assertEqual(resolve_controls("open-water", {}, 40.0, 2.0), suggested)
        self.assertEqual(
            resolve_controls("open-water", suggested, 40.0, 2.0), suggested
        )
        with self.assertRaises(ControlError) as caught:
            parse_control_overrides("open-water", {"beaufort": 1})
        self.assertIn("Unknown control", str(caught.exception))
        with self.assertRaises(ControlError) as caught:
            parse_control_overrides("open-water", {"water_gate_db": 9})
        self.assertIn("water_gate_db", str(caught.exception))
        with self.assertRaises(ControlError):
            parse_control_overrides("open-water", {"texture_window_px": 5.5})


class SeaRoughnessControlTest(unittest.TestCase):
    def test_the_split_stays_one_class_or_two_and_not_a_wave_height(self) -> None:
        flat = np.full((20, 20), -16.0, dtype=np.float32)
        calm, rough, note = split_roughness(flat, np.ones(flat.shape, dtype=bool))
        self.assertIn("less than 1.5 dB", note)
        self.assertFalse(rough.any())
        self.assertEqual(limit_for("sea-roughness"), LIMITS["sea-roughness"])
        self.assertIn("not a wave period, a wave height, or a current", note_limit())
        values = np.concatenate(
            [
                np.full(200, -20.0),
                np.full(300, -17.4),
                np.full(300, -16.5),
                np.full(200, -15.0),
            ]
        ).astype(np.float32)
        db = values.reshape(20, 50)
        water = np.ones(db.shape, dtype=bool)
        one, empty, one_note = split_roughness(db, water, split_db=1.5)
        self.assertTrue(np.array_equal(one, water))
        self.assertFalse(empty.any())
        self.assertEqual(
            one_note,
            "The two classes differ by less than 1.5 dB, "
            "so the water is drawn as one class.",
        )
        split_calm, split_rough, split_note = split_roughness(db, water, split_db=0.5)
        self.assertTrue(split_rough.any())
        self.assertTrue(split_calm.any())
        self.assertNotIn("wave", split_note.lower())
        self.assertNotIn("beaufort", split_note.lower())
        summary, layers, _strokes, legend = _single_layers(
            "sea-roughness",
            _synthetic_frame(db),
            water,
            -18.0,
            {"split_db": 0.5},
        )
        self.assertEqual(
            _labels(summary),
            {"Calm area", "Rough area", "Calm median", "Rough median"},
        )
        self.assertEqual(len(layers), 2)
        self.assertTrue(any("median" in line.lower() for line in legend))
        self.assertEqual(
            limit_for("sea-roughness", {"split_db": 0.5}), LIMITS["sea-roughness"]
        )
        self.assertEqual(
            suggested_value(_control("sea-roughness", "split_db"), 20, None), 4
        )


def note_limit() -> str:
    return LIMITS["sea-roughness"]


class BuiltUpControlTest(unittest.TestCase):
    def test_the_offset_moves_the_mask_and_the_area_is_a_one_metre_frame(
        self,
    ) -> None:
        self.assertEqual(
            limit_for("built-up", catalog_defaults("built-up")), LIMITS["built-up"]
        )
        self.assertIn("not a building height", LIMITS["built-up"])
        self.assertNotIn("ship", LIMITS["built-up"].lower())
        water = np.zeros((40, 40), dtype=bool)
        db = np.full((40, 40), -16.0, dtype=np.float32)
        db[10:16, 10:16] = -6.0
        self.assertTrue(built_up_mask(db, water, -16.0, bright_offset_db=8)[12, 12])
        self.assertFalse(built_up_mask(db, water, -16.0, bright_offset_db=16).any())
        water[:, :8] = True
        db[:, :8] = 0.0
        self.assertFalse(built_up_mask(db, water, -16.0)[2, 2])

        lone = np.full((100, 100), -16.0, dtype=np.float32)
        lone[50, 50] = 0.0
        dry = np.zeros(lone.shape, dtype=bool)
        self.assertFalse(built_up_mask(lone, dry, -16.0, col_m=1, row_m=1).any())
        self.assertTrue(built_up_mask(lone, dry, -16.0, col_m=10, row_m=10)[50, 50])
        summary, layers, _strokes, legend = _single_layers(
            "built-up",
            _synthetic_frame(db),
            water,
            -16.0,
            catalog_defaults("built-up"),
        )
        self.assertEqual(_labels(summary), {"Built-up fraction of land", "Clusters"})
        self.assertEqual(len(layers), 1)
        self.assertEqual(legend, ["Warm tint: built-up return."])


class ReturnsOnWaterControlTest(unittest.TestCase):
    def test_area_and_offset_change_the_count_and_the_bounds_stay(self) -> None:
        self.assertIn("bright radar return", LIMITS["returns-on-water"])
        self.assertNotIn("ship", LIMITS["returns-on-water"].lower())
        self.assertEqual(
            limit_for("returns-on-water", catalog_defaults("returns-on-water")),
            LIMITS["returns-on-water"],
        )
        db = np.full((20, 20), -16.0, dtype=np.float32)
        water = np.zeros(db.shape, dtype=bool)
        water[:, :2] = True
        db[8:12, 2:6] = -6.0
        loose = waterline_returns(db, water, -18.0, 2.0, 2.0, bright_offset_db=4)
        tight = waterline_returns(db, water, -18.0, 2.0, 2.0, bright_offset_db=16)
        self.assertEqual(len(loose), 1)
        self.assertEqual(tight, [])
        small = waterline_returns(
            db, water, -18.0, 2.0, 2.0, bright_offset_db=8, min_area_m2=200
        )
        large_enough = waterline_returns(
            db, water, -18.0, 2.0, 2.0, bright_offset_db=8, min_area_m2=20
        )
        self.assertEqual(small, [])
        self.assertEqual(len(large_enough), 1)

        # One pixel is under the four-pixel floor even when the area control is 4.
        speck = np.full((12, 12), -16.0, dtype=np.float32)
        speck_water = np.zeros(speck.shape, dtype=bool)
        speck_water[:, :1] = True
        speck[4, 1] = -2.0
        self.assertEqual(
            waterline_returns(
                speck, speck_water, -18.0, 10.0, 10.0, min_area_m2=4
            ),
            [],
        )

        many = np.full((8, 180), -16.0, dtype=np.float32)
        many_water = np.zeros(many.shape, dtype=bool)
        many_water[0, :] = True
        for index in range(30):
            col = 2 + index * 5
            many[1:5, col : col + 3] = -8.0 + index * 0.2
        found = waterline_returns(many, many_water, -18.0, 5.0, 5.0)
        self.assertEqual(len(found), 24)
        summary, _layers, strokes, legend = _single_layers(
            "returns-on-water",
            _synthetic_frame(db, 2.0),
            water,
            -18.0,
            catalog_defaults("returns-on-water"),
        )
        self.assertEqual(_labels(summary), {"Bright returns"})
        self.assertEqual(legend, ["Cyan marker: bright return."])
        self.assertEqual(len(strokes), 1)


class LongStructureControlTest(unittest.TestCase):
    def test_band_offset_and_length_move_the_result_and_forty_pixels_stay(
        self,
    ) -> None:
        self.assertEqual(
            limit_for("long-structure", catalog_defaults("long-structure")),
            LIMITS["long-structure"],
        )
        self.assertIn("An empty class is a valid result.", LIMITS["long-structure"])
        db, water = _vertical_bar(55)
        kept = long_structure(db, water, -18.0, 5.0, 5.0, bright_offset_db=6)
        self.assertIsNotNone(kept)
        dim = db.copy()
        dim[dim > -16] = -10.0
        self.assertIsNone(
            long_structure(dim, water, -18.0, 5.0, 5.0, bright_offset_db=12)
        )
        self.assertIsNone(
            long_structure(db, water, -18.0, 5.0, 5.0, min_length_m=1000)
        )
        # 30 pixels at 10 m is 300 m, over a 50 m control, under the 40-pixel floor.
        short_px, short_water = _vertical_bar(30)
        self.assertIsNone(
            long_structure(
                short_px, short_water, -18.0, 10.0, 10.0, min_length_m=50
            )
        )
        distant = np.full((60, 30), -16.0, dtype=np.float32)
        distant_water = np.zeros(distant.shape, dtype=bool)
        distant_water[:, :2] = True
        distant[:, 16:19] = -2.0
        self.assertIsNone(
            long_structure(distant, distant_water, -18.0, 5.0, 5.0, band_m=50)
        )
        self.assertIsNotNone(
            long_structure(distant, distant_water, -18.0, 5.0, 5.0, band_m=400)
        )
        summary, _layers, _strokes, legend = _single_layers(
            "long-structure",
            _synthetic_frame(db),
            water,
            -18.0,
            catalog_defaults("long-structure"),
        )
        self.assertTrue(
            _labels(summary) == {"Length", "Width", "Peak sigma-nought"}
            or _labels(summary) == {"Long structure"}
        )
        self.assertTrue(legend)


def _vertical_bar(rows: int) -> tuple[np.ndarray, np.ndarray]:
    db = np.full((rows, 16), -16.0, dtype=np.float32)
    water = np.zeros(db.shape, dtype=bool)
    water[:, :2] = True
    db[:, 2:5] = -2.0
    return db, water


class DwellMotionControlTest(unittest.TestCase):
    def test_the_window_and_the_gate_change_motion_and_four_pixels_stay(self) -> None:
        self.assertEqual(
            limit_for("dwell-motion", catalog_defaults("dwell-motion")),
            LIMITS["dwell-motion"],
        )
        self.assertIn("not a route", LIMITS["dwell-motion"])
        video = np.zeros((4, 16, 30), dtype=np.float32)
        video[:, 8, 4] = 10
        video[-1, 8, 14] = 100
        near = track_returns(
            video, [(8.0, 4.0)], 1.0, 1.0, 5.0, 10.0, search_radius_px=2
        )
        far = track_returns(
            video, [(8.0, 4.0)], 1.0, 1.0, 5.0, 10.0, search_radius_px=20
        )
        self.assertEqual(near[0]["motion"], "stationary during the dwell")
        self.assertEqual(far[0]["motion"], "moved")
        held = track_returns(
            video,
            [(8.0, 4.0)],
            1.0,
            1.0,
            5.0,
            10.0,
            search_radius_px=20,
            move_gate_m=100,
        )
        self.assertEqual(held[0]["motion"], "stationary during the dwell")
        short = np.zeros((3, 12, 20), dtype=np.float32)
        short[0, 5, 5] = 100
        short[-1, 5, 8] = 100
        floored = track_returns(
            short, [(5.0, 5.0)], 1.0, 1.0, 10.0, 10.0, move_gate_m=5
        )
        self.assertEqual(floored[0]["motion"], "stationary during the dwell")
        self.assertEqual(
            suggested_value(_control("dwell-motion", "search_radius_px"), None, None),
            6,
        )
        self.assertNotIn("ship", str(far[0]["motion"]))


class AmplitudeChangeControlTest(unittest.TestCase):
    def test_the_counted_areas_follow_the_controls_and_the_sentence_keeps_its_clauses(
        self,
    ) -> None:
        defaults = {"change_db": 3.0, "support_px": 8.0}
        self.assertEqual(
            limit_for("amplitude-change", defaults), LIMITS["amplitude-change"]
        )
        earlier = np.zeros((16, 16), dtype=np.float32)
        later = earlier.copy()
        later[:, 8:] = 2.0
        self.assertFalse(change_masks(earlier, later)[1].any())
        counted = change_masks(earlier, later, change_db=1)
        self.assertEqual(len(counted), 2)
        self.assertTrue(counted[1].any())
        patch = np.zeros((16, 16), dtype=np.float32)
        bright = patch.copy()
        bright[2:4, 2:5] = 6.0
        self.assertFalse(change_masks(patch, bright, support_px=8)[1].any())
        self.assertTrue(change_masks(patch, bright, support_px=4)[1].any())
        moved = limit_for("amplitude-change", {"change_db": 5, "support_px": 12})
        self.assertIn("under 5 dB", moved)
        self.assertIn("under 12 pixels", moved)
        self.assertIn("at least 5 dB", moved)
        self.assertIn("at least 12 pixels", moved)
        self.assertIn(
            "Speckle and a residual shift can still fall in those areas.", moved
        )
        self.assertNotIn("3 dB", moved)
        self.assertEqual(
            suggested_value(_control("amplitude-change", "support_px"), None, None), 8
        )


class WaterPersistenceControlTest(unittest.TestCase):
    def test_the_water_gate_changes_the_fraction_and_adds_no_season(self) -> None:
        self.assertEqual(
            limit_for("water-persistence", catalog_defaults("water-persistence")),
            LIMITS["water-persistence"],
        )
        self.assertIn("not a seasonal record", LIMITS["water-persistence"])
        self.assertEqual(list(catalog_defaults("water-persistence")), ["water_gate_db"])
        db = np.full((40, 40), -14.0, dtype=np.float32)
        db[:, :20] = -18.0
        tight = water_mask(db, water_gate_db=0.5)[0]
        wide = water_mask(db, water_gate_db=4)[0]
        self.assertGreater(
            float(persistence([wide]).mean()), float(persistence([tight]).mean())
        )
        self.assertEqual(
            suggested_value(_control("water-persistence", "water_gate_db"), 30, 5),
            1.5,
        )


class SeaStateControlTest(unittest.TestCase):
    def test_the_water_gate_changes_the_median_and_not_a_beaufort_number(self) -> None:
        self.assertIn("not a Beaufort number", LIMITS["sea-state"])
        self.assertEqual(
            limit_for("sea-state", {"water_gate_db": 3}), LIMITS["sea-state"]
        )
        frame = np.tile(np.linspace(-20, -8, 24, dtype=np.float32), (24, 1))
        tight = water_mask(frame, water_gate_db=0.5)[0]
        wide = water_mask(frame, water_gate_db=4)[0]
        low = sea_state([frame], [tight])
        high = sea_state([frame], [wide])
        self.assertIsInstance(low[0], float)
        self.assertIsInstance(high[0], float)
        self.assertNotEqual(low, high)
        self.assertNotIn("beaufort", str(high).lower())


class DarkSeaAnomalyControlTest(unittest.TestCase):
    def test_darkness_support_and_ring_move_the_mask_and_the_title_stays(self) -> None:
        self.assertIn("The title is dark sea anomaly.", LIMITS["dark-sea-anomaly"])
        self.assertEqual(
            limit_for("dark-sea-anomaly", catalog_defaults("dark-sea-anomaly")),
            LIMITS["dark-sea-anomaly"],
        )
        frame = np.full((40, 40), -13.4, dtype=np.float32)
        # Just under the 2 dB gate, with a ring under 1 dB brighter.
        frame[14:26, 14:26] = -14.2
        median = np.full(frame.shape, -12.0, dtype=np.float32)
        water = np.ones(frame.shape, dtype=bool)
        kept = dark_anomaly(frame, median, water, dark_db=2, support_px=8, ring_db=0.5)
        dark_gate = dark_anomaly(
            frame, median, water, dark_db=6, support_px=8, ring_db=0.5
        )
        ring_gate = dark_anomaly(
            frame, median, water, dark_db=2, support_px=8, ring_db=1
        )
        self.assertTrue(kept.any())
        self.assertFalse(dark_gate.any())
        self.assertFalse(ring_gate.any())
        small = np.full((24, 24), -12.0, dtype=np.float32)
        small[8:11, 8:11] = -20.0
        small_median = np.full(small.shape, -12.0, dtype=np.float32)
        small_water = np.ones(small.shape, dtype=bool)
        self.assertTrue(
            dark_anomaly(small, small_median, small_water, support_px=4).any()
        )
        self.assertFalse(
            dark_anomaly(small, small_median, small_water, support_px=16).any()
        )


class ShorelineControlTest(unittest.TestCase):
    def test_width_thickens_the_boundary_and_the_sentence_stays(self) -> None:
        self.assertIn("not a tide height", LIMITS["shoreline-series"])
        self.assertEqual(
            limit_for("shoreline-series", {"width_px": 3}), LIMITS["shoreline-series"]
        )
        mask = np.zeros((12, 12), dtype=bool)
        mask[2:10, 2:10] = True
        thin = shoreline(mask, width_px=1)
        thick = shoreline(mask, width_px=3)
        self.assertTrue(thin[2, 2])
        self.assertFalse(thin[5, 5])
        self.assertGreater(int(thick.sum()), int(thin.sum()))


class DateOfChangeControlTest(unittest.TestCase):
    def test_the_counted_pixels_follow_the_controls_and_the_sentence_keeps_its_clause(
        self,
    ) -> None:
        defaults = {"change_db": 3.0, "support_px": 8.0}
        self.assertEqual(
            limit_for("date-of-change", defaults), LIMITS["date-of-change"]
        )
        frames = [np.zeros((16, 16), dtype=np.float32) for _ in range(3)]
        frames[2] = frames[2].copy()
        frames[2][2:8, 2:8] = 4.0
        _which, keep = date_of_change(frames, change_db=3, support_px=8)
        self.assertTrue(keep[4, 4])
        _which, dropped = date_of_change(frames, change_db=6, support_px=8)
        self.assertFalse(dropped.any())
        speckled = [np.zeros((16, 16), dtype=np.float32) for _ in range(2)]
        speckled[1] = speckled[1].copy()
        speckled[1][1:3, 1:4] = 6.0
        self.assertFalse(date_of_change(speckled, support_px=8)[1].any())
        self.assertTrue(date_of_change(speckled, support_px=4)[1].any())
        moved = limit_for("date-of-change", {"change_db": 5, "support_px": 12})
        self.assertIn("by 5 dB", moved)
        self.assertIn("at least 12 pixels", moved)
        self.assertIn("A pixel is coloured only when it leaves the stack median", moved)


class RepeatReturnsControlTest(unittest.TestCase):
    def test_match_distance_merges_hits_and_six_pixels_stay(self) -> None:
        self.assertIn("moored hull", LIMITS["repeat-returns"])
        self.assertEqual(
            limit_for("repeat-returns", {"match_m": 40}), LIMITS["repeat-returns"]
        )
        first = _blob(4)
        second = _blob(14)
        masks = [np.ones(first.shape, dtype=bool), np.ones(first.shape, dtype=bool)]
        modes = [-18.0, -18.0]
        split = repeat_counts(
            [first, second], masks, modes, 10.0, 10.0, match_m=80
        )
        merged = repeat_counts(
            [first, second], masks, modes, 10.0, 10.0, match_m=200
        )
        self.assertEqual(len(split), 2)
        self.assertEqual(len(merged), 1)
        close = _blob(4)
        apart = _blob(9)
        wide_masks = [
            np.ones(close.shape, dtype=bool),
            np.ones(close.shape, dtype=bool),
        ]
        floored = repeat_counts(
            [close, apart], wide_masks, modes, 20.0, 20.0, match_m=20
        )
        self.assertEqual(len(floored), 1)


def _blob(col: int) -> np.ndarray:
    db = np.full((16, 48), -16.0, dtype=np.float32)
    db[6:10, col : col + 4] = -2.0
    return db


class SiteActivityControlTest(unittest.TestCase):
    def test_offset_and_minimum_change_the_cluster_and_the_classes_stay(self) -> None:
        self.assertEqual(
            limit_for("site-activity", catalog_defaults("site-activity")),
            LIMITS["site-activity"],
        )
        frame = np.full((16, 16), -20.0, dtype=np.float32)
        median = frame.copy()
        frame[2:5, 2:4] = -8.0
        kept, left = site_activity(
            frame, median, -20.0, bright_offset_db=8, min_pixels=4
        )
        too_small, _left = site_activity(
            frame, median, -20.0, bright_offset_db=8, min_pixels=8
        )
        too_dim, _left = site_activity(
            frame, median, -20.0, bright_offset_db=16, min_pixels=2
        )
        self.assertTrue(kept.any())
        self.assertFalse(left.any())
        self.assertFalse(too_small.any())
        self.assertFalse(too_dim.any())
        self.assertEqual(
            limit_for("site-activity", {"bright_offset_db": 12, "min_pixels": 8}),
            LIMITS["site-activity"],
        )


class StackMeanControlTest(unittest.TestCase):
    def test_there_is_no_control_and_five_scenes_still_lock_it(self) -> None:
        self.assertEqual(TOOL_CONTROLS["stack-mean"], ())
        self.assertEqual(parse_control_overrides("stack-mean", None), {})
        with self.assertRaises(ControlError) as caught:
            parse_control_overrides("stack-mean", {"change_db": 3})
        self.assertIn("Unknown control", str(caught.exception))
        self.assertIn("at least five", LIMITS["stack-mean"])
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scene_id = "ICEYE_TEST_20260211T000000Z_1_X1_SM"
            OpenWaterPictureTest()._write_scene(root, scene_id, dark=True)
            with patch("scene.toolkit.catalog.scene_dir", _rooted(root)):
                views = {item.id: item for item in tools_for_scene(scene_id)}
            self.assertTrue(views["stack-mean"].locked)
            self.assertIn("five", views["stack-mean"].reason)
            public = views["stack-mean"].to_public()
            self.assertEqual(public["controls"], [])
            water = views["open-water"].to_public()["controls"]
            self.assertIsInstance(water, list)
            assert isinstance(water, list)
            self.assertEqual(
                [item["id"] for item in water],
                ["water_gate_db", "texture_window_px", "max_hole_px"],
            )
            gate = water[0]
            assert isinstance(gate, dict)
            self.assertEqual(gate["value"], 1.5)
            self.assertEqual(gate["min"], 0.5)
            self.assertEqual(gate["max"], 4)


if __name__ == "__main__":
    unittest.main()
