"""Facts: the open scene, its tool locks, and catalogue scenes not yet downloaded."""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import Field

from scene.catalog import CatalogRecord
from scene.paths import LISBON_SCENE_ID
from scene.report.chains import PlanChoice, ReportChains, chains_or_none
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


class FakeChatModel(BaseChatModel):
    """A chat model that answers from memory and records every prompt it is given."""

    plan: object = Field(default_factory=dict)
    text: str = "phrased"
    seen: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(
        self, messages: list[BaseMessage], *args: Any, **kwargs: Any
    ) -> ChatResult:
        self.seen.append(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(self.text))])

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable[Any, Any]:
        """Answer the plan call with ``plan`` and keep the prompt it was given."""

        def reply(value: Any) -> object:
            self.seen.append(value.to_messages())
            return self.plan

        return RunnableLambda(reply)

    def prompt_text(self) -> str:
        """Every message of the last prompt, joined."""

        return "\n".join(str(message.content) for message in self.seen[-1])


class ChainsOrNoneTests(unittest.TestCase):
    """The key gate. No test here invokes a model or opens a socket."""

    @contextmanager
    def _environment(self, env_text: str | None, **environ: str) -> Iterator[None]:
        """A project root holding ``env_text`` as .env, and exactly ``environ``."""

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            if env_text is not None:
                (root / ".env").write_text(env_text, encoding="utf-8")
            with (
                patch("scene.analyze.project_root", return_value=root),
                patch.dict(os.environ, environ, clear=True),
            ):
                yield

    def test_is_none_when_the_key_is_absent(self) -> None:
        with self._environment(None), patch("scene.report.chains.ChatOpenAI") as chat:
            self.assertIsNone(chains_or_none())
        chat.assert_not_called()

    def test_is_none_when_dotenv_has_no_key(self) -> None:
        with (
            self._environment("OTHER=1\n# OPENAI_API_KEY=commented\n"),
            patch("scene.report.chains.ChatOpenAI") as chat,
        ):
            self.assertIsNone(chains_or_none())
        chat.assert_not_called()

    def test_is_none_when_the_key_is_blank(self) -> None:
        for env_text, environ in (
            ("OPENAI_API_KEY=\n", {}),
            (None, {"OPENAI_API_KEY": "   "}),
        ):
            with self.subTest(env_text=env_text, environ=environ):
                with (
                    self._environment(env_text, **environ),
                    patch("scene.report.chains.ChatOpenAI") as chat,
                ):
                    self.assertIsNone(chains_or_none())
                chat.assert_not_called()

    def test_builds_the_model_from_dotenv_with_the_pinned_settings(self) -> None:
        with (
            self._environment("OPENAI_API_KEY=from-dotenv\n"),
            patch(
                "scene.report.chains.ChatOpenAI", return_value=FakeChatModel()
            ) as chat,
        ):
            chains = chains_or_none()
        self.assertIsInstance(chains, ReportChains)
        chat.assert_called_once_with(model="gpt-4o-mini", temperature=0)

    def test_an_existing_environment_value_wins_over_dotenv(self) -> None:
        with (
            self._environment("OPENAI_API_KEY=\n", OPENAI_API_KEY="from-environment"),
            patch(
                "scene.report.chains.ChatOpenAI", return_value=FakeChatModel()
            ) as chat,
        ):
            self.assertIsInstance(chains_or_none(), ReportChains)
        chat.assert_called_once()


class ReportChainsTests(unittest.TestCase):
    """Prompts and result shapes, with a fake chat model. Nothing is sent anywhere."""

    def setUp(self) -> None:
        self.facts = _facts(
            [
                {
                    **_tool("open-water"),
                    "label": "Open water",
                    "description": "Dark water as a share of the frame.",
                    "overview_url": "/overview-url-leak.png",
                    "measurement": "measurement-leak",
                    "briefing_html": "<p>briefing-leak</p>",
                },
                _tool("amplitude-change", partners=[NEIGHBOUR_ID]),
            ],
            [CATALOGUE_ROW],
        )

    def test_plan_returns_exactly_the_keys_the_validator_reads(self) -> None:
        model = FakeChatModel(
            plan=PlanChoice(
                tools=["open-water"], catalogue_only=[CACHED_ID], partner_id=None
            )
        )
        plan = ReportChains(model).plan("How dark is the water?", self.facts)
        self.assertEqual(
            plan,
            {
                "tools": ["open-water"],
                "catalogue_only": [CACHED_ID],
                "partner_id": None,
            },
        )

    def test_plan_does_not_drop_ids_and_validate_plan_does(self) -> None:
        raw: dict[str, Any] = {
            "tools": ["open-water", "invented"],
            "catalogue_only": ["ICEYE_Z_20260301T000000Z_1_X1_SM"],
            "partner_id": "nobody",
        }
        for model_output in (raw, PlanChoice(**raw)):
            with self.subTest(kind=type(model_output).__name__):
                chains = ReportChains(FakeChatModel(plan=model_output))
                plan = chains.plan("Anything?", self.facts)
                self.assertEqual(plan, raw)
                self.assertEqual(
                    validate_plan(self.facts, plan).selected, ["open-water"]
                )

    def test_plan_prompt_names_the_question_the_tools_and_the_catalogue(self) -> None:
        model = FakeChatModel(
            plan={"tools": [], "catalogue_only": [], "partner_id": None}
        )
        ReportChains(model).plan("How dark is the water?", self.facts)
        prompt = model.prompt_text()
        for expected in (
            "How dark is the water?",
            "open-water",
            "Dark water as a share of the frame.",
            "amplitude-change",
            NEIGHBOUR_ID,
            CACHED_ID,
            "only the tools that answer the question",
        ):
            self.assertIn(expected, prompt)
        for leak in ("overview-url-leak", "measurement-leak", "briefing-leak"):
            self.assertNotIn(leak, prompt)

    def test_scene_note_is_in_the_plan_prompt_only_for_the_lisbon_scene(self) -> None:
        note = "No detector labelled this frame."
        for scene_id, present in ((LISBON_SCENE_ID, True), (OPEN_ID, False)):
            with self.subTest(scene_id=scene_id):
                model = FakeChatModel(plan={})
                facts = dataclasses.replace(self.facts, scene_id=scene_id)
                ReportChains(model).plan("What is here?", facts)
                self.assertEqual(note in model.prompt_text(), present)

    def test_phrase_prompt_carries_the_measurement_limit_and_scene_fields(self) -> None:
        model = FakeChatModel(text="The water covers 12.5 % of the frame.")
        measurement = {
            "tool_id": "open-water",
            "summary": [{"label": "Water area", "value": "12.5 %"}],
            "limit": "Dark pixels are not proof of water.",
            "overview_path": "/data/overview-path-leak.png",
        }
        facts = dataclasses.replace(self.facts, overview_metres=(1.25, 2.5))
        text = ReportChains(model).phrase("How dark?", facts, measurement)
        self.assertEqual(text, "The water covers 12.5 % of the frame.")
        prompt = model.prompt_text()
        for expected in (
            "How dark?",
            "Water area",
            "12.5 %",
            "Dark pixels are not proof of water.",
            "stripmap",
            "26.0",
            "ascending",
            "right",
            "1.25",
            "2.5",
            "limit sentence unchanged",
            "ship",
            "spill",
            "tide height",
            "cause",
        ):
            self.assertIn(expected, prompt)
        self.assertNotIn("overview-path-leak", prompt)

    def test_phraser_system_prompt_says_a_bright_mark_stays_a_radar_return(
        self,
    ) -> None:
        """The claim limit sits in the prompt, next to the forbid list."""
        model = FakeChatModel()
        ReportChains(model).phrase(
            "How dark?", self.facts, {"summary": [], "limit": "A limit."}
        )
        self.assertIn(
            "A bright mark stays a bright radar return.", model.prompt_text()
        )

    def test_phrase_prompt_is_not_given_other_tools_or_raster_data(self) -> None:
        model = FakeChatModel()
        ReportChains(model).phrase(
            "How dark?",
            self.facts,
            {"summary": [], "limit": "A limit."},
        )
        prompt = model.prompt_text()
        for leak in ("amplitude-change", "measurement-leak", CACHED_ID, ".tif", ".png"):
            self.assertNotIn(leak, prompt)

    def test_phrase_says_the_scale_is_unavailable_when_there_is_none(self) -> None:
        model = FakeChatModel()
        ReportChains(model).phrase(
            "How dark?", self.facts, {"summary": [], "limit": "A limit."}
        )
        self.assertIn("null", model.prompt_text())


if __name__ == "__main__":
    unittest.main()
