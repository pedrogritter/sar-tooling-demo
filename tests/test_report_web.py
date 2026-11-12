"""Report routes and the PDF: one run, the stored document, and its HTML."""

from __future__ import annotations

import ast
import json
import os
import tempfile
import threading
import unittest
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from scene.belt.catalog import ToolView, analysis_dir, tool_spec
from scene.jobs import MeasurementJobManager
from scene.report.facts import ReportFacts
from scene.report.select import STACK_SCOPE
from scene.report.store import Report, ReportSection, ReportStore
from scene.web import AppState, HttpResponse, dispatch
from tests import test_belt

SCENE = "ICEYE_A_20260211T000000Z_1_X1_SM"
PARTNER = "ICEYE_B_20260212T000000Z_1_X1_SM"
WATER_LIMIT = "Shadow, tarmac, and sand are dark for the same reason."
LOCK_REASON = "This collect has no dwell stack."
STACK_LOCK_LINE = "This stack tool needs another calibrated scene."
STACK_LOCK = "The stack mean needs five calibrated scenes."
NO_KEY = "Set OPENAI_API_KEY to ask a question."
JOKE = "JOKE ABOUT A SHIP"
LEAD = "SYNTHESIS LEAD"


def _view(
    tool_id: str,
    *,
    locked: bool = False,
    reason: str = "",
    partners: tuple[str, ...] = (),
) -> ToolView:
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
        tools=[],
        catalogue_only=[],
    )


def _default_views() -> list[ToolView]:
    return [
        _view("open-water"),
        _view("sea-roughness"),
        _view("dwell-motion", locked=True, reason=LOCK_REASON),
        _view("amplitude-change", partners=(PARTNER,)),
        _view("water-persistence", partners=(PARTNER,)),
        _view("sea-state", locked=True, reason=STACK_LOCK_LINE, partners=(PARTNER,)),
        _view("stack-mean", locked=True, reason=STACK_LOCK, partners=(PARTNER,)),
    ]


class FakeChains:
    """Order, narrator, and synthesis that never leave the process."""

    def __init__(self) -> None:
        self.ordered: list[list[str]] = []

    def order(
        self, facts: ReportFacts, tools: Sequence[Mapping[str, str]]
    ) -> list[str]:
        ids = [str(tool["id"]) for tool in tools]
        self.ordered.append(ids)
        return ids

    def narrate(self, facts: ReportFacts, tool: Mapping[str, str]) -> str:
        del facts
        return f"Working on {tool['id']}."

    def synthesize(
        self,
        facts: ReportFacts,
        partner_id: str | None,
        sections: Sequence[ReportSection],
        glossary: str,
        *,
        stack_scope: str | None,
        matched_dates: int | None,
    ) -> str:
        del facts, partner_id, sections, glossary, stack_scope, matched_dates
        return "A hedged reading."


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
        self.views = _default_views()
        self.ran: list[tuple[str, str | None]] = []

    @contextmanager
    def patched(self, chains: object | None = None) -> Iterator[None]:
        rooted = test_belt._rooted(self.root)

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
            patch("scene.report.run.report_facts", lambda scene_id: _facts()),
            patch("scene.report.select.tools_for_scene", lambda scene_id: self.views),
            patch("scene.belt.run.run_tool", run_tool),
            patch("scene.report.run._glossary", lambda: "GLOSSARY TEXT"),
            patch("scene.report.chains.load_local_env", lambda: None),
            patch("scene.report.chains.chains_or_none", lambda: chains),
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

    def allow_key(self) -> None:
        os.environ["OPENAI_API_KEY"] = "test-key"


class RunRouteTest(WebBase):
    PATH = f"/api/scenes/{SCENE}/report/run"

    def test_409_without_a_key_and_no_job_starts(self) -> None:
        with self.patched(chains=None):
            response = self.post(self.PATH, {"partner_id": None})
        self.assertEqual(response.status, 409)
        self.assertIn(NO_KEY, response.body.decode())
        self.assertEqual(self.manager.current().status, "idle")

    def test_400_for_a_missing_or_malformed_partner(self) -> None:
        with self.patched(chains=FakeChains()):
            missing = self.post(self.PATH, {})
            empty = self.post(self.PATH, {"partner_id": ""})
            number = self.post(self.PATH, {"partner_id": 3})
            walk = self.post(self.PATH, {"partner_id": "../x"})
            not_json = self.post(self.PATH, b"nope")
        for response in (missing, empty, number, walk, not_json):
            self.assertEqual(response.status, 400)
        self.assertEqual(self.manager.current().status, "idle")

    def test_400_when_the_partner_is_not_eligible(self) -> None:
        with self.patched(chains=FakeChains()):
            response = self.post(self.PATH, {"partner_id": "ICEYE_NOPE_1"})
        self.assertEqual(response.status, 400)
        self.assertIn("not a scene this report can compare", response.body.decode())
        self.assertEqual(self.manager.current().status, "idle")
        self.assertEqual(self.ran, [])

    def test_400_when_nothing_can_run_and_no_job_starts(self) -> None:
        self.views = [
            _view("open-water", locked=True, reason="This tool reads grd-cog.tif."),
            _view("dwell-motion", locked=True, reason=LOCK_REASON),
        ]
        with self.patched(chains=FakeChains()):
            response = self.post(self.PATH, {"partner_id": None})
        self.assertEqual(response.status, 400)
        text = response.body.decode()
        self.assertIn("No tool can run for this scene.", text)
        self.assertIn("grd-cog.tif", text)
        self.assertEqual(self.manager.current().status, "idle")

    def test_no_partner_runs_single_and_motion_tools_only(self) -> None:
        with self.patched(chains=FakeChains()):
            self.allow_key()
            response = self.post(self.PATH, {"partner_id": None})
            self.assertEqual(response.status, 202)
            self.wait()
            document = json.loads(self.get(f"/api/scenes/{SCENE}/report").body)
        self.assertEqual(self.manager.current().status, "done")
        self.assertEqual(document["question"], "")
        self.assertIsNone(document["partner_id"])
        self.assertEqual(document["phase"], "done")
        self.assertEqual(document["tool_order"], ["open-water", "sea-roughness"])
        self.assertEqual(document["synthesis_source"], "model")
        self.assertEqual(document["synthesis_md"], "A hedged reading.")
        by_tool = {item["tool_id"]: item for item in document["sections"]}
        self.assertEqual(by_tool["open-water"]["status"], "done")
        self.assertEqual(by_tool["dwell-motion"]["status"], "locked")
        self.assertEqual(by_tool["dwell-motion"]["briefing_md"], LOCK_REASON)
        self.assertNotIn("amplitude-change", by_tool)
        self.assertNotIn("water-persistence", by_tool)
        self.assertNotIn("sea-state", by_tool)
        self.assertNotIn("stack-mean", by_tool)
        self.assertEqual(
            self.ran, [("open-water", None), ("sea-roughness", None)]
        )
        self.assertNotIn(
            "waiting", {item["status"] for item in document["sections"]}
        )

    def test_a_partner_runs_change_and_keeps_locked_stack_sections(self) -> None:
        with self.patched(chains=FakeChains()):
            self.allow_key()
            response = self.post(self.PATH, {"partner_id": PARTNER})
            self.assertEqual(response.status, 202)
            self.wait()
            document = json.loads(self.get(f"/api/scenes/{SCENE}/report").body)
        self.assertEqual(document["partner_id"], PARTNER)
        self.assertIn(STACK_SCOPE, document["synthesis_md"])
        self.assertIn(("amplitude-change", PARTNER), self.ran)
        self.assertIn(("water-persistence", None), self.ran)
        self.assertNotIn(("sea-state", None), self.ran)
        self.assertNotIn(("stack-mean", None), self.ran)
        self.assertNotIn(("dwell-motion", None), self.ran)
        self.assertNotIn("sea-state", document["tool_order"])
        self.assertNotIn("stack-mean", document["tool_order"])
        by_tool = {item["tool_id"]: item for item in document["sections"]}
        self.assertEqual(by_tool["amplitude-change"]["partner_id"], PARTNER)
        self.assertEqual(by_tool["sea-state"]["status"], "locked")
        self.assertEqual(by_tool["sea-state"]["briefing_md"], STACK_LOCK_LINE)
        self.assertEqual(by_tool["stack-mean"]["status"], "locked")
        self.assertEqual(by_tool["stack-mean"]["briefing_md"], STACK_LOCK)

    def test_409_while_a_measurement_is_running(self) -> None:
        release = threading.Event()
        started = threading.Event()

        def runner(on_step: Callable[[int, str], None]) -> None:
            started.set()
            release.wait(timeout=5)

        self.manager.start_report(runner)
        self.assertTrue(started.wait(timeout=5))
        try:
            with self.patched(chains=FakeChains()):
                self.allow_key()
                response = self.post(self.PATH, {"partner_id": None})
        finally:
            release.set()
        self.assertEqual(response.status, 409)
        self.assertIn(b"running", response.body)
        self.assertNotIn(NO_KEY.encode(), response.body)

    def test_removed_plan_and_amplitude_routes_are_not_found(self) -> None:
        with self.patched(chains=FakeChains()):
            plan = self.post(f"/api/scenes/{SCENE}/report/plan", {"partner_id": None})
            amplitude = self.post(
                f"/api/scenes/{SCENE}/report/amplitude", {"partner_id": PARTNER}
            )
        self.assertEqual(plan.status, 404)
        self.assertEqual(amplitude.status, 404)


class GetReportTest(WebBase):
    def test_an_unsaved_report_has_the_new_fields_and_no_sections(self) -> None:
        with self.patched():
            response = self.get(f"/api/scenes/{SCENE}/report")
        self.assertEqual(response.status, 200)
        document = json.loads(response.body)
        self.assertEqual(document["sections"], [])
        self.assertEqual(document["question"], "")
        self.assertIsNone(document["partner_id"])
        self.assertEqual(document["phase"], "done")
        self.assertEqual(document["tool_order"], [])
        self.assertEqual(document["synthesis_md"], "")
        self.assertEqual(document["synthesis_source"], "belt")

    def test_an_older_file_is_returned_with_defaults(self) -> None:
        with self.patched():
            path = ReportStore(SCENE).path
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "scene_id": SCENE,
                        "question": "What is on the water?",
                        "sections": [
                            {
                                "tool_id": "open-water",
                                "status": "waiting",
                                "measurement": None,
                                "briefing_md": "The comparison has not been made.",
                                "briefing_source": "belt",
                                "overview_url": None,
                                "partner_id": None,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            response = self.get(f"/api/scenes/{SCENE}/report")
        document = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(document["question"], "What is on the water?")
        self.assertEqual(document["phase"], "done")
        self.assertEqual(document["sections"][0]["status"], "waiting")
        self.assertEqual(document["sections"][0]["progress_note"], "")

    def test_partial_sections_are_returned(self) -> None:
        with self.patched():
            store = ReportStore(SCENE)
            store.save(store.new([_section("open-water", "running")]))
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
            store.save(store.new([_section("open-water", "done")]))
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
    status: str,
    briefing: str = "",
    measurement: dict[str, object] | None = None,
    partner_id: str | None = None,
    progress_note: str = "",
) -> ReportSection:
    return ReportSection(
        tool_id=tool_id,
        status=status,  # type: ignore[arg-type]
        measurement=measurement,
        briefing_md=briefing,
        briefing_source="belt",
        overview_url=None,
        partner_id=partner_id,
        progress_note=progress_note,
    )


class PdfTest(WebBase):
    def test_the_html_has_the_synthesis_the_image_and_the_limit_but_not_the_joke(
        self,
    ) -> None:
        captured: dict[str, str] = {}

        def fake_write(document: str) -> bytes:
            captured["html"] = document
            return b"%PDF-1.7 fake"

        with self.patched(chains=None):
            report = Report(
                scene_id=SCENE,
                question="",
                partner_id=PARTNER,
                phase="done",
                tool_order=["open-water", "sea-roughness"],
                synthesis_md=LEAD,
                synthesis_source="model",
                sections=[
                    _section("dwell-motion", "locked", LOCK_REASON),
                    _section(
                        "open-water",
                        "done",
                        "belt text that is not the joke",
                        {
                            "summary": [{"label": "Water area", "value": "1.20 km²"}],
                            "limit": WATER_LIMIT,
                        },
                        progress_note=JOKE,
                    ),
                    _section(
                        "sea-roughness", "failed", "sea-roughness could not run."
                    ),
                ],
            )
            ReportStore(SCENE).save(report)
            folder = analysis_dir(SCENE, "open-water")
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "overview.png").write_bytes(b"png")
            with (
                patch(
                    "scene.report.chains.chains_or_none",
                    side_effect=AssertionError("the PDF path must not build a model"),
                ),
                patch("scene.report.pdf.write_pdf", fake_write),
            ):
                response = self.get(f"/api/scenes/{SCENE}/report.pdf")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "application/pdf")
        self.assertEqual(response.body, b"%PDF-1.7 fake")
        document = captured["html"]
        self.assertIn(LEAD, document)
        self.assertIn(WATER_LIMIT, document)
        self.assertIn("overview.png", document)
        self.assertIn("1.20 km²", document)
        self.assertIn(LOCK_REASON, document)
        self.assertIn("sea-roughness could not run.", document)
        self.assertIn(SCENE, document)
        self.assertNotIn(JOKE, document)
        self.assertIn("@page", document)
        self.assertIn("counter(page)", document)
        self.assertIn("break-before: page", document)

    def test_a_missing_report_is_a_404(self) -> None:
        with self.patched():
            response = self.get(f"/api/scenes/{SCENE}/report.pdf")
        self.assertEqual(response.status, 404)

    def test_text_outside_latin_1_is_kept_in_the_html(self) -> None:
        captured: dict[str, str] = {}

        def fake_write(document: str) -> bytes:
            captured["html"] = document
            return b"%PDF-1.7 fake"

        with self.patched():
            ReportStore(SCENE).save(
                Report(
                    scene_id=SCENE,
                    question="Why \u2014 \u03c3\u00b0 \u2192 water?",
                    synthesis_md="Dark \u201cwater\u201d \u2192 calm",
                    sections=[_section("open-water", "done", "Dark \u201cwater\u201d")],
                )
            )
            with patch("scene.report.pdf.write_pdf", fake_write):
                response = self.get(f"/api/scenes/{SCENE}/report.pdf")
        self.assertEqual(response.status, 200)
        self.assertIn("Dark \u201cwater\u201d \u2192 calm", captured["html"])
        self.assertIn("\u03c3", captured["html"])

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
            self.assertNotIn("fpdf", name)
            self.assertNotIn("weasyprint", name)


class ModelKeyRouteTest(WebBase):
    """GET and POST /api/report/key. The response never contains the key."""

    def tearDown(self) -> None:
        from scene.report import chains

        chains._session_key = None

    def test_get_reports_unset_and_does_not_start_a_job(self) -> None:
        with self.patched():
            response = self.get("/api/report/key")
        self.assertEqual(response.status, 200)
        self.assertEqual(
            json.loads(response.body),
            {"configured": False, "source": "unset"},
        )
        self.assertEqual(self.manager.current().status, "idle")

    def test_post_keeps_a_session_key_out_of_the_response(self) -> None:
        with self.patched():
            saved = self.post("/api/report/key", {"api_key": "sk-session-value"})
            self.assertEqual(saved.status, 200)
            self.assertEqual(
                json.loads(saved.body),
                {"configured": True, "source": "session"},
            )
            self.assertNotIn(b"sk-session-value", saved.body)
            again = self.get("/api/report/key")
            self.assertEqual(
                json.loads(again.body),
                {"configured": True, "source": "session"},
            )
            self.assertNotIn(b"sk-session-value", again.body)
            replaced = self.post("/api/report/key", {"api_key": "sk-replaced"})
            self.assertEqual(json.loads(replaced.body)["source"], "session")
            self.assertEqual(os.environ.get("OPENAI_API_KEY"), "sk-replaced")

    def test_post_rejects_a_blank_spaced_or_huge_key(self) -> None:
        with self.patched():
            self.assertEqual(self.post("/api/report/key", {}).status, 400)
            self.assertEqual(
                self.post("/api/report/key", {"api_key": "  "}).status, 400
            )
            self.assertEqual(
                self.post("/api/report/key", {"api_key": "sk test"}).status, 400
            )
            self.assertEqual(self.post("/api/report/key", b"nope").status, 400)
            self.assertEqual(
                self.post("/api/report/key", {"api_key": "k" * 513}).status, 400
            )
            self.assertNotIn("OPENAI_API_KEY", os.environ)

    def test_an_environment_key_is_not_replaced(self) -> None:
        with self.patched():
            os.environ["OPENAI_API_KEY"] = "from-environment"
            status = json.loads(self.get("/api/report/key").body)
            self.assertEqual(status, {"configured": True, "source": "environment"})
            refused = self.post("/api/report/key", {"api_key": "sk-other"})
            self.assertEqual(refused.status, 409)
            self.assertIn("already set", refused.body.decode())
            self.assertNotIn(b"sk-other", refused.body)
            self.assertNotIn(b"from-environment", refused.body)
            self.assertEqual(os.environ["OPENAI_API_KEY"], "from-environment")


if __name__ == "__main__":
    unittest.main()
