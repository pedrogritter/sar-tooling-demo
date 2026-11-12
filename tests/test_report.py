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
from unittest.mock import call, patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import Field

from scene.belt.catalog import ToolView, tool_spec
from scene.belt.run import LIMITS
from scene.catalog import CatalogRecord
from scene.paths import LISBON_SCENE_ID, project_root
from scene.report.chains import (
    NARRATOR_SYSTEM,
    SYNTHESIS_SYSTEM,
    OrderChoice,
    ReportChains,
    chains_or_none,
    model_key_source,
    remember_model_key,
)
from scene.report.facts import ReportFacts, report_facts
from scene.report.select import STACK_SCOPE, IneligiblePartner, choose_tools
from scene.report.store import ReportSection
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
    **extra: object,
) -> dict[str, object]:
    """The public keys a report reads from tools_for_scene().to_public()."""

    return {
        "id": tool_id,
        "label": extra.get("label", tool_id),
        "description": extra.get("description", ""),
        "locked": locked,
        "reason": reason,
        "needs_partner": partners is not None,
        "partners": partners or [],
        **extra,
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


def _view(
    tool_id: str,
    *,
    locked: bool = False,
    reason: str = "",
    partners: tuple[str, ...] = (),
) -> ToolView:
    """A belt view with the real kind, label, and description for ``tool_id``."""

    spec = tool_spec(tool_id)
    return ToolView(
        id=spec.id,
        label=spec.label,
        category=spec.category,
        description=spec.description,
        locked=locked,
        reason=reason if locked else "",
        needs_partner=spec.kind == "pair",
        partners=partners,
        overview_url=None,
        measurement=None,
        briefing_html=None,
    )


class ChooseToolsTests(unittest.TestCase):
    """Code chooses the set. No partner leaves change and stack out, locks included."""

    def _views(self) -> list[ToolView]:
        return [
            _view("open-water"),
            _view(
                "dwell-motion",
                locked=True,
                reason="This collect has no dwell stack.",
            ),
            _view("amplitude-change", partners=(NEIGHBOUR_ID,)),
            _view("water-persistence", partners=(NEIGHBOUR_ID,)),
            _view(
                "sea-state",
                locked=True,
                reason="This stack tool needs another calibrated scene.",
                partners=(NEIGHBOUR_ID,),
            ),
            _view(
                "stack-mean",
                locked=True,
                reason="The stack mean needs five calibrated scenes.",
                partners=(NEIGHBOUR_ID,),
            ),
        ]

    def test_no_partner_omits_change_and_stack_including_their_lock_lines(self) -> None:
        with patch("scene.report.select.tools_for_scene", return_value=self._views()):
            chosen = choose_tools(OPEN_ID, None)
        self.assertEqual(
            [tool.id for tool in chosen.tools], ["open-water", "dwell-motion"]
        )
        self.assertTrue(chosen.tools[1].locked)
        self.assertIsNone(chosen.partner_id)
        self.assertIsNone(chosen.matched_dates)
        self.assertEqual(chosen.runnable_ids, ["open-water"])

    def test_a_partner_adds_change_and_keeps_locked_stack_tools(self) -> None:
        with patch("scene.report.select.tools_for_scene", return_value=self._views()):
            chosen = choose_tools(OPEN_ID, NEIGHBOUR_ID)
        self.assertEqual(
            [tool.id for tool in chosen.tools],
            [
                "open-water",
                "dwell-motion",
                "amplitude-change",
                "water-persistence",
                "sea-state",
                "stack-mean",
            ],
        )
        locked = {tool.id: tool for tool in chosen.tools if tool.locked}
        self.assertEqual(
            locked["sea-state"].reason,
            "This stack tool needs another calibrated scene.",
        )
        self.assertEqual(
            locked["stack-mean"].reason,
            "The stack mean needs five calibrated scenes.",
        )
        self.assertEqual(chosen.matched_dates, 2)
        self.assertNotIn("sea-state", chosen.runnable_ids)
        self.assertNotIn("stack-mean", chosen.runnable_ids)

    def test_locked_stack_tools_are_sections_and_are_not_a_comparison(self) -> None:
        views = [
            _view("open-water"),
            _view("amplitude-change", partners=(NEIGHBOUR_ID,)),
            _view(
                "water-persistence",
                locked=True,
                reason="This stack tool is locked.",
                partners=(NEIGHBOUR_ID,),
            ),
            _view(
                "stack-mean",
                locked=True,
                reason="The stack mean is locked.",
                partners=(NEIGHBOUR_ID,),
            ),
        ]
        with patch("scene.report.select.tools_for_scene", return_value=views):
            chosen = choose_tools(OPEN_ID, NEIGHBOUR_ID)
        self.assertEqual(
            [(tool.id, tool.locked) for tool in chosen.tools],
            [
                ("open-water", False),
                ("amplitude-change", False),
                ("water-persistence", True),
                ("stack-mean", True),
            ],
        )
        self.assertEqual(chosen.tools[2].reason, "This stack tool is locked.")
        self.assertIsNone(chosen.matched_dates)
        self.assertEqual(chosen.runnable_ids, ["open-water", "amplitude-change"])

    def test_an_ineligible_or_locked_partner_is_rejected(self) -> None:
        views = self._views()
        with patch("scene.report.select.tools_for_scene", return_value=views):
            with self.assertRaises(IneligiblePartner):
                choose_tools(OPEN_ID, "ICEYE_Z_20260301T000000Z_1_X1_SM")
        locked = [
            _view("open-water"),
            _view(
                "amplitude-change",
                locked=True,
                reason=LOCK_REASON,
                partners=(NEIGHBOUR_ID,),
            ),
        ]
        with (
            patch("scene.report.select.tools_for_scene", return_value=locked),
            self.assertRaises(IneligiblePartner),
        ):
            choose_tools(OPEN_ID, NEIGHBOUR_ID)


class GlossaryTests(unittest.TestCase):
    def test_glossary_repeats_the_belt_limits_and_the_named_terms(self) -> None:
        text = (project_root() / "content" / "sar_glossary.md").read_text(
            encoding="utf-8"
        )
        lowered = text.lower()
        for term in (
            "sigma-nought",
            "layover",
            "incidence",
            "speckle",
            "look side",
            "double-bounce",
            "overview scale",
        ):
            self.assertIn(term, lowered)
        for sentence in LIMITS.values():
            self.assertIn(sentence, text)
        self.assertIn(STACK_SCOPE, text)


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
        self.assertEqual(
            chat.call_args_list,
            [
                call(model="gpt-4o-mini", temperature=0),
                call(model="gpt-4o-mini", temperature=0.7),
            ],
        )

    def test_an_existing_environment_value_wins_over_dotenv(self) -> None:
        with (
            self._environment("OPENAI_API_KEY=\n", OPENAI_API_KEY="from-environment"),
            patch(
                "scene.report.chains.ChatOpenAI", return_value=FakeChatModel()
            ) as chat,
        ):
            self.assertIsInstance(chains_or_none(), ReportChains)
        self.assertEqual(chat.call_count, 2)

    def tearDown(self) -> None:
        from scene.report import chains

        chains._session_key = None

    def test_source_follows_the_environment(self) -> None:
        with self._environment(None):
            self.assertEqual(model_key_source(), "unset")
        with self._environment(None, OPENAI_API_KEY="from-environment"):
            self.assertEqual(model_key_source(), "environment")

    def test_a_remembered_key_is_session_and_builds_the_model(self) -> None:
        with (
            self._environment(None),
            patch(
                "scene.report.chains.ChatOpenAI", return_value=FakeChatModel()
            ) as chat,
        ):
            remember_model_key("from-session")
            self.assertEqual(model_key_source(), "session")
            self.assertIsInstance(chains_or_none(), ReportChains)
        self.assertEqual(
            chat.call_args_list,
            [
                call(model="gpt-4o-mini", temperature=0),
                call(model="gpt-4o-mini", temperature=0.7),
            ],
        )

    def test_remember_rejects_a_blank_key(self) -> None:
        with self.assertRaises(ValueError):
            remember_model_key("   ")


def _runnable_tool() -> dict[str, str]:
    return {
        "id": "open-water",
        "label": "Open water",
        "description": "Dark water as a share of the frame.",
        "overview_url": "/overview-url-leak.png",
    }


class ReportChainsTests(unittest.TestCase):
    """Prompts and result shapes, with a fake chat model. Nothing is sent anywhere."""

    def setUp(self) -> None:
        self.facts = _facts(
            [
                {
                    **_tool(
                        "open-water",
                        label="Open water",
                        description="Dark water as a share of the frame.",
                    ),
                    "overview_url": "/overview-url-leak.png",
                    "measurement": "measurement-leak",
                    "briefing_html": "<p>briefing-leak</p>",
                },
                _tool("amplitude-change", partners=[NEIGHBOUR_ID]),
            ],
            [CATALOGUE_ROW],
        )
        self.steady = FakeChatModel()
        self.narrator = FakeChatModel()

    def chains(self, steady: FakeChatModel | None = None) -> ReportChains:
        return ReportChains(steady or self.steady, self.narrator)

    def test_order_returns_the_model_list_even_when_it_is_not_a_permutation(
        self,
    ) -> None:
        raw: dict[str, Any] = {"tools": ["open-water", "invented"]}
        for model_output in (raw, OrderChoice(tools=["open-water", "invented"])):
            with self.subTest(kind=type(model_output).__name__):
                model = FakeChatModel(plan=model_output)
                ordered = ReportChains(model, model).order(
                    self.facts, [_runnable_tool()]
                )
                self.assertEqual(ordered, ["open-water", "invented"])

    def test_order_prompt_names_the_tools_and_drops_rasters_and_the_catalogue(
        self,
    ) -> None:
        model = FakeChatModel(plan={"tools": ["open-water"]})
        facts = dataclasses.replace(self.facts, scene_id=LISBON_SCENE_ID)
        ReportChains(model, model).order(facts, [_runnable_tool()])
        prompt = model.prompt_text()
        for expected in (
            "open-water",
            "Dark water as a share of the frame.",
            "Use each id once",
            LISBON_SCENE_ID,
        ):
            self.assertIn(expected, prompt)
        note = (project_root() / "content" / "scene_note.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(note.splitlines()[2], prompt)
        for leak in (
            "overview-url-leak",
            "measurement-leak",
            "briefing-leak",
            CACHED_ID,
            ".tif",
            ".png",
        ):
            self.assertNotIn(leak, prompt)

    def test_a_non_list_order_raises_so_the_run_can_fall_back(self) -> None:
        model = FakeChatModel(plan={"tools": "open-water"})
        with self.assertRaises(ValueError):
            ReportChains(model, model).order(self.facts, [_runnable_tool()])

    def test_narrator_prompt_names_the_mode_and_does_not_invent_a_target(self) -> None:
        model = FakeChatModel(text="Dark water on this stripmap pass, nothing named.")
        text = ReportChains(self.steady, model).narrate(self.facts, _runnable_tool())
        self.assertEqual(text, "Dark water on this stripmap pass, nothing named.")
        prompt = model.prompt_text()
        for expected in (
            "stripmap",
            "Open water",
            "ship",
            "spill",
            "tide",
            "building",
        ):
            self.assertIn(expected, prompt)
        self.assertNotIn("overview-url-leak", prompt)
        self.assertNotIn(".png", prompt)
        self.assertNotIn("humorous", prompt)
        self.assertNotIn("humorous", NARRATOR_SYSTEM)

    def test_synthesis_prompt_carries_rows_limits_failures_locks_and_the_glossary(
        self,
    ) -> None:
        model = FakeChatModel(text="A hedged reading.")
        facts = dataclasses.replace(self.facts, overview_metres=(1.25, 2.5))
        done = ReportSection(
            tool_id="open-water",
            status="done",
            measurement={
                "summary": [{"label": "Water area", "value": "12.5 %"}],
                "limit": "Dark pixels are not proof of water.",
                "overview_path": "/data/overview-path-leak.png",
            },
            briefing_md="belt briefing",
            briefing_source="belt",
            overview_url="/api/overview-url-leak.png",
            partner_id=None,
            progress_note="A joke about a ship that must stay off the page.",
        )
        locked = ReportSection(
            tool_id="dwell-motion",
            status="locked",
            measurement=None,
            briefing_md=LOCK_REASON,
            briefing_source="belt",
            overview_url=None,
            partner_id=None,
        )
        failed = ReportSection(
            tool_id="sea-roughness",
            status="failed",
            measurement=None,
            briefing_md="sea-roughness could not run.",
            briefing_source="belt",
            overview_url=None,
            partner_id=None,
        )
        text = ReportChains(model, self.narrator).synthesize(
            facts,
            NEIGHBOUR_ID,
            [done, locked, failed],
            "Sigma-nought is radar brightness.",
            stack_scope=STACK_SCOPE,
            matched_dates=2,
        )
        self.assertEqual(text, "A hedged reading.")
        prompt = model.prompt_text()
        for expected in (
            "12.5 %",
            "Dark pixels are not proof of water.",
            LOCK_REASON,
            "sea-roughness could not run.",
            "Sigma-nought is radar brightness.",
            NEIGHBOUR_ID,
            "stripmap",
            "1.25",
            "2.5",
            STACK_SCOPE,
            "hedged reading",
            "ship",
            "spill",
            "tide height",
            "building height",
            "A bright return stays a bright radar return.",
        ):
            self.assertIn(expected, prompt)
        for leak in (
            "overview-path-leak",
            "overview-url-leak",
            "A joke about a ship",
            CACHED_ID,
            ".tif",
            ".png",
            "No detector labelled this frame.",
            "stack of only two dates",
        ):
            self.assertNotIn(leak, prompt)
        self.assertNotIn("stack of only two dates", SYNTHESIS_SYSTEM)
        for banned in ("two dates", "second date", "stack", "partner", "cause"):
            self.assertNotIn(banned, SYNTHESIS_SYSTEM)

    def test_single_scene_synthesis_prompt_does_not_invite_a_second_date(
        self,
    ) -> None:
        model = FakeChatModel(text="A hedged reading.")
        ReportChains(model, self.narrator).synthesize(
            self.facts,
            None,
            [],
            "Sigma-nought is radar brightness.",
            stack_scope=None,
            matched_dates=None,
        )
        prompt = model.prompt_text()
        self.assertIn(
            "Do not mention a second date, a stack, a partner, or a cause.",
            prompt,
        )
        self.assertNotIn("stack of only two dates", prompt)
        self.assertNotIn("partner_id", prompt)
        self.assertNotIn("stack_scope", prompt)
        self.assertNotIn("matched_dates", prompt)


if __name__ == "__main__":
    unittest.main()
