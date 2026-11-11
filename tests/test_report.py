"""Facts: the open scene, its tool locks, and catalogue scenes not yet downloaded."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from scene.catalog import CatalogRecord
from scene.report.facts import ReportFacts, report_facts
from scene.report.schema import ReportPlan
from scene.report.validate import validate_plan
from tests import test_belt

OPEN_ID = "ICEYE_A_20260211T000000Z_1_X1_SM"
NEIGHBOUR_ID = "ICEYE_B_20260212T000000Z_1_X1_SM"
CACHED_ID = "ICEYE_C_20260213T000000Z_1_X1_SM"
UNCACHED_ID = "ICEYE_D_20260214T000000Z_1_X1_SM"
OTHER_LOOK_ID = "ICEYE_E_20260215T000000Z_1_X1_SM"
DISJOINT_ID = "ICEYE_F_20260216T000000Z_1_X1_SM"
WIDE_INCIDENCE_ID = "ICEYE_G_20260217T000000Z_1_X1_SM"

# The footprint the test scene writer gives every scene folder.
SCENE_BBOX = (-16.9, 28.0, -16.6, 28.3)


def _record(scene_id: str, **changes: object) -> CatalogRecord:
    """A cached catalogue row that shares look and footprint with the open scene."""

    fields: dict[str, object] = {
        "scene_id": scene_id,
        "href": f"https://example.test/{scene_id}.json",
        "acquired_at": f"{scene_id.split('_')[2]}",
        "satellite": "ICEYE-X1",
        "product_code": "SM",
        "cached": True,
        "mode": "stripmap",
        "incidence_angle": 26.0,
        "bbox": SCENE_BBOX,
        "orbit": "ascending",
        "look": "right",
    }
    fields.update(changes)
    return CatalogRecord(**fields)  # type: ignore[arg-type]


def _write_scene(root: Path, scene_id: str) -> None:
    test_belt.OpenWaterPictureTest()._write_scene(root, scene_id, dark=True)


@contextmanager
def _patched(root: Path) -> Iterator[None]:
    """Point every scene folder lookup at ``root``, as tests/test_web.py does."""

    rooted = test_belt._rooted(root)
    with (
        patch("scene.belt.catalog.scene_dir", rooted),
        patch("scene.report.facts.scene_dir", rooted),
    ):
        yield


class FactsTests(unittest.TestCase):
    def test_catalogue_only_lists_cached_same_look_scenes_without_a_folder(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_scene(root, OPEN_ID)
            _write_scene(root, NEIGHBOUR_ID)
            records = [
                _record(CACHED_ID),
                _record(UNCACHED_ID, cached=False),
                _record(NEIGHBOUR_ID),
                _record(OPEN_ID),
            ]
            with _patched(root):
                facts = report_facts(OPEN_ID, records=records)
            self.assertEqual(
                facts.catalogue_only,
                [{"scene_id": CACHED_ID, "collected_at": "20260213T000000Z"}],
            )

    def test_catalogue_only_needs_the_same_look_and_an_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_scene(root, OPEN_ID)
            records = [
                _record(OTHER_LOOK_ID, look="left"),
                _record(DISJOINT_ID, bbox=(10.0, 40.0, 10.3, 40.3)),
                _record(WIDE_INCIDENCE_ID, incidence_angle=29.0),
                _record(CACHED_ID, orbit=None),
            ]
            with _patched(root):
                facts = report_facts(OPEN_ID, records=records)
            self.assertEqual(facts.catalogue_only, [])

    def test_scene_fields_and_tool_locks_come_from_the_open_folder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_scene(root, OPEN_ID)
            _write_scene(root, NEIGHBOUR_ID)
            with _patched(root):
                facts = report_facts(OPEN_ID, records=[])
            self.assertEqual(facts.scene_id, OPEN_ID)
            self.assertEqual(facts.mode, "stripmap")
            self.assertEqual(facts.incidence, 26.0)
            self.assertEqual(facts.orbit, "ascending")
            self.assertEqual(facts.look, "right")
            self.assertEqual(facts.band, "X")
            self.assertEqual(facts.polarization, "VV")
            self.assertEqual(facts.collected_at, "2026-02-11T00:00:00Z")
            tools = {tool["id"]: tool for tool in facts.tools}
            self.assertFalse(tools["open-water"]["locked"])
            self.assertFalse(tools["amplitude-change"]["locked"])
            self.assertEqual(tools["amplitude-change"]["partners"], [NEIGHBOUR_ID])
            self.assertTrue(tools["dwell-motion"]["locked"])

    def test_overview_metres_come_from_the_grd_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_scene(root, OPEN_ID)
            with _patched(root):
                facts = report_facts(OPEN_ID, records=[])
            assert facts.overview_metres is not None
            column, row = facts.overview_metres
            # 0.001 degree of longitude at 28 N, and of latitude.
            self.assertAlmostEqual(column, 98.2, delta=0.5)
            self.assertAlmostEqual(row, 110.5, delta=0.5)

    def test_overview_metres_is_none_without_the_sidecar_or_the_grd(self) -> None:
        for missing in ("grd-json.json", "grd-cog.tif"):
            with self.subTest(missing=missing):
                with tempfile.TemporaryDirectory() as raw:
                    root = Path(raw)
                    _write_scene(root, OPEN_ID)
                    (root / "scenes" / OPEN_ID / missing).unlink()
                    with _patched(root):
                        facts = report_facts(OPEN_ID, records=[])
                    self.assertIsNone(facts.overview_metres)

    def test_omitted_records_read_the_local_index_and_never_open_a_socket(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_scene(root, OPEN_ID)
            index = root / "catalog-index.json"
            row = _record(CACHED_ID)
            index.write_text(
                json.dumps(
                    {
                        "fetched_at": "2026-02-11T00:00:00+00:00",
                        "records": [
                            {
                                "scene_id": row.scene_id,
                                "href": row.href,
                                "acquired_at": row.acquired_at,
                                "cached": True,
                                "incidence_angle": row.incidence_angle,
                                "bbox": list(SCENE_BBOX),
                                "orbit": row.orbit,
                                "look": row.look,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with (
                _patched(root),
                patch("scene.report.facts.catalog_index_path", lambda: index),
                patch(
                    "socket.socket.connect",
                    side_effect=AssertionError("facts must not use the network"),
                ),
            ):
                facts = report_facts(OPEN_ID)
            self.assertEqual(
                [item["scene_id"] for item in facts.catalogue_only], [CACHED_ID]
            )

    def test_omitted_records_without_an_index_file_is_an_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_scene(root, OPEN_ID)
            with (
                _patched(root),
                patch(
                    "scene.report.facts.catalog_index_path",
                    lambda: root / "absent.json",
                ),
            ):
                facts = report_facts(OPEN_ID)
            self.assertEqual(facts.catalogue_only, [])


def _tool(
    tool_id: str,
    locked: bool = False,
    reason: str | None = None,
    partners: list[str] | None = None,
) -> dict[str, object]:
    """The public keys a report reads from tools_for_scene().to_public()."""

    return {
        "id": tool_id,
        "locked": locked,
        "reason": reason,
        "needs_partner": partners is not None,
        "partners": partners or [],
    }


def _facts(
    tools: list[dict[str, object]], catalogue_only: list[dict[str, str]] | None = None
) -> ReportFacts:
    """Facts built in memory. Validation reads only tools and catalogue_only."""

    return ReportFacts(
        scene_id=OPEN_ID,
        mode="stripmap",
        incidence=26.0,
        orbit="ascending",
        look="right",
        band="X",
        polarization="VV",
        collected_at="2026-02-11T00:00:00Z",
        overview_metres=None,
        tools=tools,
        catalogue_only=catalogue_only or [],
    )


LOCK_REASON = "Needs a scene with the same look."
CATALOGUE_ROW = {"scene_id": CACHED_ID, "collected_at": "20260213T000000Z"}


class ValidatePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = _facts(
            [
                _tool("open-water"),
                _tool("amplitude-change", partners=[NEIGHBOUR_ID]),
                _tool("dwell-motion", locked=True, reason=LOCK_REASON),
            ],
            [CATALOGUE_ROW],
        )

    def test_an_invented_id_is_dropped(self) -> None:
        plan = validate_plan(self.facts, {"tools": ["open-water", "made-up-tool"]})
        self.assertIsInstance(plan, ReportPlan)
        self.assertEqual(plan.selected, ["open-water"])

    def test_a_locked_id_is_dropped_but_still_reported_as_locked(self) -> None:
        plan = validate_plan(self.facts, {"tools": ["open-water", "dwell-motion"]})
        self.assertEqual(plan.selected, ["open-water"])
        self.assertEqual(
            [(item.id, item.reason) for item in plan.locked],
            [("dwell-motion", LOCK_REASON)],
        )

    def test_locked_tools_are_listed_even_when_the_model_names_nothing(self) -> None:
        plan = validate_plan(self.facts, {})
        self.assertEqual(plan.selected, [])
        self.assertEqual([item.id for item in plan.locked], ["dwell-motion"])

    def test_amplitude_change_lands_in_waiting_with_a_partner_suggestion(self) -> None:
        plan = validate_plan(
            self.facts,
            {"tools": ["open-water", "amplitude-change"], "partner_id": NEIGHBOUR_ID},
        )
        self.assertEqual(plan.selected, ["open-water"])
        self.assertEqual(plan.waiting, ["amplitude-change"])
        self.assertEqual(plan.partner_id, NEIGHBOUR_ID)

    def test_a_partner_that_is_not_eligible_is_dropped(self) -> None:
        for partner in ("ICEYE_Z_20260301T000000Z_1_X1_SM", 7, None):
            with self.subTest(partner=partner):
                plan = validate_plan(
                    self.facts,
                    {"tools": ["amplitude-change"], "partner_id": partner},
                )
                self.assertEqual(plan.waiting, ["amplitude-change"])
                self.assertIsNone(plan.partner_id)

    def test_a_locked_amplitude_change_has_no_waiting_and_no_partner(self) -> None:
        facts = _facts(
            [_tool("amplitude-change", locked=True, reason=LOCK_REASON, partners=[])]
        )
        plan = validate_plan(
            facts, {"tools": ["amplitude-change"], "partner_id": NEIGHBOUR_ID}
        )
        self.assertEqual(plan.waiting, [])
        self.assertIsNone(plan.partner_id)
        self.assertEqual(plan.selected, [])

    def test_amplitude_change_that_is_not_named_is_not_waiting(self) -> None:
        plan = validate_plan(self.facts, {"tools": ["open-water"]})
        self.assertEqual(plan.waiting, [])
        self.assertIsNone(plan.partner_id)

    def test_a_catalogue_id_the_facts_do_not_list_is_dropped(self) -> None:
        plan = validate_plan(
            self.facts,
            {"catalogue_only": [CACHED_ID, "ICEYE_Z_20260301T000000Z_1_X1_SM"]},
        )
        self.assertEqual(plan.catalogue_only, [CATALOGUE_ROW])

    def test_malformed_model_output_gives_an_empty_plan(self) -> None:
        malformed: list[object] = [
            None,
            "text",
            [],
            {"tools": "open-water"},
            {"tools": [1, None]},
        ]
        for raw in malformed:
            with self.subTest(raw=raw):
                plan = validate_plan(self.facts, raw)
                self.assertEqual(plan.selected, [])
                self.assertEqual(plan.waiting, [])
                self.assertEqual(plan.catalogue_only, [])
                self.assertIsNone(plan.partner_id)

    def test_repeated_ids_are_kept_once(self) -> None:
        plan = validate_plan(self.facts, {"tools": ["open-water", "open-water"]})
        self.assertEqual(plan.selected, ["open-water"])


if __name__ == "__main__":
    unittest.main()
