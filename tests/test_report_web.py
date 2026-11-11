"""Report routes and the PDF: the plan, the run, the amplitude step, the document."""

from __future__ import annotations

import ast
import io
import json
import os
import tempfile
import threading
import unittest
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader

from scene.belt.catalog import analysis_dir
from scene.jobs import MeasurementJobManager
from scene.report.facts import ReportFacts
from scene.report.store import ReportSection, ReportStore
from scene.web import AppState, HttpResponse, dispatch
from tests import test_belt

SCENE = "ICEYE_A_20260211T000000Z_1_X1_SM"
PARTNER = "ICEYE_B_20260212T000000Z_1_X1_SM"
QUESTION = "What is on the water?"
WATER_LIMIT = "Shadow, tarmac, and sand are dark for the same reason."
LOCK_REASON = "Needs a scene with the same look."
WAITING = "The comparison has not been made."
NO_KEY = "Set OPENAI_API_KEY to ask a question."


def _tool(
    tool_id: str,
    locked: bool = False,
    reason: str | None = None,
    partners: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": tool_id,
        "label": tool_id.replace("-", " ").title(),
        "description": "",
        "locked": locked,
        "reason": reason or "",
        "needs_partner": partners is not None,
        "partners": partners or [],
    }


def _facts() -> ReportFacts:
    return ReportFacts(
        scene_id=SCENE,
        mode="stripmap",
        incidence=26.0,
        orbit="ascending",
        look="right",
        band="X",
        polarization="VV",
        collected_at="2026-02-11T00:00:00Z",
        overview_metres=None,
        tools=[
            _tool("open-water"),
            _tool("sea-roughness"),
            _tool("amplitude-change", partners=[PARTNER]),
            _tool("ship-detection", locked=True, reason=LOCK_REASON),
        ],
        catalogue_only=[],
    )


class _View:
    """What ``tools_for_scene`` returns: the fields the routes read."""

    def __init__(self, tool: dict[str, object]) -> None:
        partners = tool["partners"]
        assert isinstance(partners, list)
        self.id = str(tool["id"])
        self.locked = bool(tool["locked"])
        self.partners = tuple(str(item) for item in partners)


class FakeChains:
    """A planner and a phraser that never leave the process."""

    def __init__(self, raw: dict[str, object]) -> None:
        self.raw = raw
        self.planned: list[str] = []

    def plan(self, question: str, facts: ReportFacts) -> dict[str, object]:
        self.planned.append(question)
        return self.raw

    def phrase(self, question: str, facts: object, measurement: Any) -> str:
        return f"Plain words. {measurement['limit']}"


class WebBase(unittest.TestCase):
    """A temp scene folder, patched path roots, and a manager that stays local."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "scenes" / SCENE).mkdir(parents=True)
        (self.root / "scenes" / SCENE / "stac.json").write_text("{}", "utf-8")
        self.manager = MeasurementJobManager(output_dir=self.root / "out")
        self.state: AppState = None  # type: ignore[assignment]
        self.facts = _facts()
        self.ran: list[tuple[str, str | None]] = []

    @contextmanager
    def patched(self, chains: object | None = None) -> Iterator[None]:
        rooted = test_belt._rooted(self.root)
        views = [_View(tool) for tool in self.facts.tools]

        def run_tool(
            scene_id: str,
            tool_id: str,
            on_step: Callable[[int, str], None],
            partner_id: str | None = None,
        ) -> None:
            self.ran.append((tool_id, partner_id))
            folder = analysis_dir(scene_id, tool_id, partner_id)
            folder.mkdir(parents=True, exist_ok=True)
            payload = {
                "tool_id": tool_id,
                "summary": [{"label": "Water area", "value": "1.20 km²"}],
                "limit": WATER_LIMIT,
            }
            (folder / "measurements.json").write_text(json.dumps(payload), "utf-8")
            (folder / "briefing.md").write_text("# Belt\n\nbelt text\n", "utf-8")

        env = {
            key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("scene.web.scene_dir", rooted),
            patch("scene.report.store.scene_dir", rooted),
            patch("scene.belt.catalog.scene_dir", rooted),
            patch("scene.web.report_facts", lambda scene_id: self.facts),
            patch("scene.web.tools_for_scene", lambda scene_id: views),
            patch("scene.report.run.report_facts", lambda scene_id: self.facts),
            patch("scene.belt.run.run_tool", run_tool),
            patch("scene.report.chains.load_local_env", lambda: None),
            patch(
                "scene.report.chains.chains_or_none",
                lambda: chains,
            ),
        ):
            yield

    def post(self, path: str, payload: object) -> HttpResponse:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return dispatch("POST", path, body, self.state, self.manager)

    def get(self, path: str) -> HttpResponse:
        return dispatch("GET", path, b"", self.state, self.manager)

    def wait(self) -> None:
        thread = self.manager._thread
        assert thread is not None
        thread.join(timeout=5)


class PlanRouteTest(WebBase):
    PATH = f"/api/scenes/{SCENE}/report/plan"

    def test_409_without_a_key_and_no_job_starts(self) -> None:
        with self.patched(chains=None):
            response = self.post(self.PATH, {"question": QUESTION})
        self.assertEqual(response.status, 409)
        self.assertIn(NO_KEY, response.body.decode())
        self.assertEqual(self.manager.current().status, "idle")

    def test_400_for_an_empty_missing_or_long_question(self) -> None:
        chains = FakeChains({"tools": []})
        with self.patched(chains=chains):
            self.assertEqual(self.post(self.PATH, {"question": "  "}).status, 400)
            self.assertEqual(self.post(self.PATH, {}).status, 400)
            self.assertEqual(self.post(self.PATH, {"question": 7}).status, 400)
            self.assertEqual(self.post(self.PATH, b"nope").status, 400)
            self.assertEqual(self.post(self.PATH, {"question": "q" * 2049}).status, 400)
            self.assertEqual(self.post(self.PATH, {"question": "q" * 2048}).status, 200)

    def test_the_validated_plan_is_returned_and_nothing_runs(self) -> None:
        chains = FakeChains(
            {
                "tools": [
                    "open-water",
                    "invented",
                    "ship-detection",
                    "amplitude-change",
                ],
                "catalogue_only": [],
                "partner_id": PARTNER,
            }
        )
        with self.patched(chains=chains):
            response = self.post(self.PATH, {"question": QUESTION})
        self.assertEqual(response.status, 200)
        plan = json.loads(response.body)
        self.assertEqual(plan["selected"], ["open-water"])
        self.assertEqual(plan["waiting"], ["amplitude-change"])
        self.assertEqual(plan["partner_id"], PARTNER)
        self.assertEqual([item["id"] for item in plan["locked"]], ["ship-detection"])
        self.assertEqual(chains.planned, [QUESTION])
        self.assertEqual(self.manager.current().status, "idle")
        self.assertEqual(self.ran, [])

    def test_a_failing_chain_returns_a_fixed_sentence_not_its_text(self) -> None:
        secret = "sk-secret-123 quota exceeded for org-acme"

        class Failing:
            def plan(self, question: str, facts: ReportFacts) -> dict[str, object]:
                raise RuntimeError(secret)

        with self.patched(chains=Failing()):
            with self.assertLogs("scene", level="ERROR") as logged:
                response = self.post(self.PATH, {"question": QUESTION})
        self.assertEqual(response.status, 502)
        self.assertEqual(
            response.body.decode().strip(), "The report plan could not be written."
        )
        self.assertNotIn("sk-secret", response.body.decode())
        self.assertIn(secret, "\n".join(logged.output))

    def test_404_for_a_scene_that_is_not_on_disk(self) -> None:
        with self.patched(chains=None):
            missing = self.post(
                "/api/scenes/ICEYE_NOPE_1_X/report/plan", {"question": QUESTION}
            )
        self.assertEqual(missing.status, 404)


class RunRouteTest(WebBase):
    PATH = f"/api/scenes/{SCENE}/report/run"

    def test_400_for_an_invented_tool_id(self) -> None:
        with self.patched():
            response = self.post(
                self.PATH, {"question": QUESTION, "tool_ids": ["open-water", "nope"]}
            )
        self.assertEqual(response.status, 400)
        self.assertEqual(self.manager.current().status, "idle")

    def test_400_for_a_locked_id_a_bad_body_or_an_empty_choice(self) -> None:
        with self.patched():
            locked = self.post(
                self.PATH, {"question": QUESTION, "tool_ids": ["ship-detection"]}
            )
            not_list = self.post(self.PATH, {"question": QUESTION, "tool_ids": "x"})
            empty = self.post(self.PATH, {"question": QUESTION, "tool_ids": []})
            no_question = self.post(
                self.PATH, {"question": "", "tool_ids": ["open-water"]}
            )
        for response in (locked, not_list, empty, no_question):
            self.assertEqual(response.status, 400)
        self.assertEqual(self.manager.current().status, "idle")

    def test_a_valid_run_stores_the_question_and_every_section(self) -> None:
        with self.patched(chains=FakeChains({})):
            response = self.post(
                self.PATH,
                {"question": QUESTION, "tool_ids": ["open-water", "amplitude-change"]},
            )
            self.assertEqual(response.status, 202)
            self.wait()
            report = self.get(f"/api/scenes/{SCENE}/report")
        self.assertEqual(self.manager.current().status, "done")
        document = json.loads(report.body)
        self.assertEqual(document["question"], QUESTION)
        by_tool = {item["tool_id"]: item for item in document["sections"]}
        self.assertEqual(by_tool["open-water"]["status"], "done")
        self.assertEqual(by_tool["amplitude-change"]["status"], "waiting")
        self.assertEqual(by_tool["ship-detection"]["status"], "locked")
        self.assertEqual(self.ran, [("open-water", None)])

    def test_409_while_a_measurement_is_running(self) -> None:
        release = threading.Event()
        started = threading.Event()

        def runner(on_step: Callable[[int, str], None]) -> None:
            started.set()
            release.wait(timeout=5)

        self.manager.start_report(runner)
        self.assertTrue(started.wait(timeout=5))
        try:
            with self.patched():
                response = self.post(
                    self.PATH, {"question": QUESTION, "tool_ids": ["open-water"]}
                )
        finally:
            release.set()
        self.assertEqual(response.status, 409)


class AmplitudeRouteTest(WebBase):
    PATH = f"/api/scenes/{SCENE}/report/amplitude"

    def _first_report(self) -> None:
        self.post(
            f"/api/scenes/{SCENE}/report/run",
            {"question": QUESTION, "tool_ids": ["open-water", "amplitude-change"]},
        )
        self.wait()

    def test_400_when_the_partner_is_not_eligible_or_malformed(self) -> None:
        with self.patched(chains=FakeChains({})):
            self._first_report()
            for partner in ("ICEYE_C_1", "../x", "", None, 3):
                response = self.post(self.PATH, {"partner_id": partner})
                self.assertEqual(response.status, 400, partner)
            self.assertEqual(self.post(self.PATH, b"[]").status, 400)

    def test_an_eligible_partner_replaces_only_the_waiting_section(self) -> None:
        with self.patched(chains=FakeChains({})):
            self._first_report()
            before = ReportStore(SCENE).load()
            assert before is not None
            response = self.post(self.PATH, {"partner_id": PARTNER})
            self.assertEqual(response.status, 202)
            self.wait()
            after = ReportStore(SCENE).load()
        assert after is not None
        by_tool = {item.tool_id: item for item in after.sections}
        self.assertEqual(by_tool["amplitude-change"].status, "done")
        self.assertEqual(by_tool["amplitude-change"].partner_id, PARTNER)
        original = {item.tool_id: item for item in before.sections}
        self.assertEqual(by_tool["open-water"], original["open-water"])
        self.assertIn(("amplitude-change", PARTNER), self.ran)

    def test_409_while_a_measurement_is_running(self) -> None:
        release = threading.Event()
        started = threading.Event()

        def runner(on_step: Callable[[int, str], None]) -> None:
            started.set()
            release.wait(timeout=5)

        self.manager.start_report(runner)
        self.assertTrue(started.wait(timeout=5))
        try:
            with self.patched():
                response = self.post(self.PATH, {"partner_id": PARTNER})
        finally:
            release.set()
        self.assertEqual(response.status, 409)


class GetReportTest(WebBase):
    def test_an_unsaved_report_has_no_sections(self) -> None:
        with self.patched():
            response = self.get(f"/api/scenes/{SCENE}/report")
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.body)["sections"], [])

    def test_partial_sections_are_returned(self) -> None:
        with self.patched():
            store = ReportStore(SCENE)
            store.save(store.new(QUESTION, [_section("open-water", "running")]))
            response = self.get(f"/api/scenes/{SCENE}/report")
        document = json.loads(response.body)
        self.assertEqual(document["sections"][0]["status"], "running")

    def test_a_corrupt_file_is_a_clear_500(self) -> None:
        with self.patched():
            path = ReportStore(SCENE).path
            path.parent.mkdir(parents=True)
            path.write_text("{not json", "utf-8")
            with self.assertLogs("scene", level="ERROR"):
                response = self.get(f"/api/scenes/{SCENE}/report")
        self.assertEqual(response.status, 500)

    def test_a_pdf_that_cannot_be_built_returns_a_fixed_sentence(self) -> None:
        secret = "reportlab exploded at /home/user/secret.png"
        with self.patched():
            store = ReportStore(SCENE)
            store.save(store.new(QUESTION, [_section("open-water", "done")]))
            with (
                patch("scene.web.build_pdf", side_effect=RuntimeError(secret)),
                self.assertLogs("scene", level="ERROR") as logged,
            ):
                response = self.get(f"/api/scenes/{SCENE}/report.pdf")
        self.assertEqual(response.status, 500)
        self.assertEqual(
            response.body.decode().strip(), "The report PDF could not be written."
        )
        self.assertIn(secret, "\n".join(logged.output))

    def test_jobs_current_is_still_the_step_sentence(self) -> None:
        with self.patched():
            response = self.get("/api/jobs/current")
        self.assertEqual(json.loads(response.body)["status"], "idle")


def _section(
    tool_id: str,
    status: Any,
    briefing: str = "",
    measurement: dict[str, object] | None = None,
    partner_id: str | None = None,
) -> ReportSection:
    return ReportSection(
        tool_id=tool_id,
        status=status,
        measurement=measurement,
        briefing_md=briefing,
        briefing_source="belt",
        overview_url=None,
        partner_id=partner_id,
    )


def _pdf_text(body: bytes) -> str:
    reader = PdfReader(io.BytesIO(body))
    return " ".join(" ".join(page.extract_text().split()) for page in reader.pages)


class PdfTest(WebBase):
    def _save_report(self) -> None:
        store = ReportStore(SCENE)
        sections = [
            _section("ship-detection", "locked", LOCK_REASON),
            _section("amplitude-change", "waiting", WAITING),
            _section(
                "open-water",
                "done",
                "# Open water\n\nThe water is **dark**. " + WATER_LIMIT,
                {
                    "summary": [{"label": "Water area", "value": "1.20 km²"}],
                    "limit": WATER_LIMIT,
                },
            ),
            _section("sea-roughness", "failed", "sea-roughness could not run."),
        ]
        store.save(store.new(QUESTION, sections))

    def test_the_pdf_text_has_the_limit_the_lock_and_the_waiting_sentence(self) -> None:
        with self.patched(chains=None):
            self._save_report()
            folder = analysis_dir(SCENE, "open-water")
            folder.mkdir(parents=True, exist_ok=True)
            buffer = io.BytesIO()
            Image.new("RGB", (8, 8), "gray").save(buffer, "PNG")
            (folder / "overview.png").write_bytes(buffer.getvalue())
            # The model must not be reached on this path.
            with patch(
                "scene.report.chains.chains_or_none",
                side_effect=AssertionError("the PDF path must not build a model"),
            ):
                response = self.get(f"/api/scenes/{SCENE}/report.pdf")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "application/pdf")
        self.assertTrue(response.body.startswith(b"%PDF"))
        text = _pdf_text(response.body)
        self.assertIn(WATER_LIMIT, text)
        self.assertIn(LOCK_REASON, text)
        self.assertIn(WAITING, text)
        self.assertIn(SCENE, text)
        self.assertIn(QUESTION, text)
        self.assertIn("Water area", text)
        self.assertIn("1.20 km²", text)
        self.assertIn("sea-roughness could not run.", text)
        pages = PdfReader(io.BytesIO(response.body)).pages
        self.assertEqual(sum(len(page.images) for page in pages), 1)

    def test_a_missing_report_is_a_404(self) -> None:
        with self.patched():
            response = self.get(f"/api/scenes/{SCENE}/report.pdf")
        self.assertEqual(response.status, 404)

    def test_text_outside_latin_1_does_not_break_the_document(self) -> None:
        with self.patched():
            store = ReportStore(SCENE)
            store.save(
                store.new(
                    "Why \u2014 \u03c3\u00b0 \u2192 water?",
                    [
                        _section(
                            "open-water", "done", "Dark \u201cwater\u201d \u2192 calm"
                        )
                    ],
                )
            )
            response = self.get(f"/api/scenes/{SCENE}/report.pdf")
        self.assertEqual(response.status, 200)
        self.assertIn("Dark", _pdf_text(response.body))

    def test_pdf_module_imports_no_model_library(self) -> None:
        source = Path(__file__).resolve().parents[1] / "src/scene/report/pdf.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
        for name in names:
            self.assertNotIn("langchain", name)
            self.assertNotIn("openai", name)
            self.assertNotIn("chains", name)


if __name__ == "__main__":
    unittest.main()
