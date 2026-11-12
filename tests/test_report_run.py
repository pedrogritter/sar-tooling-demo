"""Store and run: order, each section, and the lead are written as they land."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from scene.belt.catalog import analysis_dir, tool_spec
from scene.jobs import JobAlreadyRunningError, MeasurementJobManager
from scene.report.facts import ReportFacts
from scene.report.run import run_report
from scene.report.select import STACK_SCOPE, IncludedTool, ToolSet
from scene.report.store import Report, ReportSection, ReportStore
from tests import test_belt

SCENE = "ICEYE_A_20260211T000000Z_1_X1_SM"
PARTNER = "ICEYE_B_20260212T000000Z_1_X1_SM"
OTHER = "ICEYE_C_20260213T000000Z_1_X1_SM"

WATER_LIMIT = "Shadow, tarmac, and sand are dark for the same reason."
ROUGH_LIMIT = "This split is roughness, not a wave height."
CHANGE_LIMIT = "The picture is a shared stretch."
FACTS = ReportFacts(
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

Steps = list[tuple[int, str]]


class FakeChains:
    """A stand-in for ReportChains. Order echoes the ids unless told otherwise."""

    def __init__(self) -> None:
        self.order_result: list[str] | None = None
        self.order_error: BaseException | None = None
        self.note = "Working on the dark water."
        self.note_error: BaseException | None = None
        self.lead = "A hedged reading of the rows."
        self.lead_error: BaseException | None = None
        self.order_calls: list[list[str]] = []
        self.narrate_calls: list[str] = []
        self.glossary = ""
        self.stack_scope: str | None = None
        self.phase_during_order: str | None = None

    def order(
        self, facts: ReportFacts, tools: Sequence[Mapping[str, str]]
    ) -> list[str]:
        stored = ReportStore(SCENE).load()
        self.phase_during_order = None if stored is None else stored.phase
        ids = [str(tool["id"]) for tool in tools]
        self.order_calls.append(ids)
        if self.order_error is not None:
            raise self.order_error
        if self.order_result is None:
            return list(ids)
        return list(self.order_result)

    def narrate(self, facts: ReportFacts, tool: Mapping[str, str]) -> str:
        self.narrate_calls.append(str(tool["id"]))
        if self.note_error is not None:
            raise self.note_error
        return self.note

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
        del facts, partner_id, sections, matched_dates
        self.glossary = glossary
        self.stack_scope = stack_scope
        if self.lead_error is not None:
            raise self.lead_error
        return self.lead


def _included(
    tool_id: str, *, locked: bool = False, reason: str = ""
) -> IncludedTool:
    spec = tool_spec(tool_id)
    return IncludedTool(
        id=spec.id,
        label=spec.label,
        description=spec.description,
        kind=spec.kind,
        locked=locked,
        reason=reason,
    )


def _set(
    tools: list[IncludedTool],
    partner_id: str | None = None,
    matched_dates: int | None = None,
) -> ToolSet:
    return ToolSet(partner_id, tuple(tools), matched_dates)


class RunnerBase(unittest.TestCase):
    """Scene folders under a temp root, and a fake ``run_tool``."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.ran: list[tuple[str, str | None]] = []
        self.steps: Steps = []
        self.limits = {
            "open-water": WATER_LIMIT,
            "sea-roughness": ROUGH_LIMIT,
            "amplitude-change": CHANGE_LIMIT,
            "water-persistence": "Two dates are a pair, not a seasonal record.",
        }
        self.sections_seen_by_run_tool: list[list[str]] = []
        self.orders_seen: list[list[str]] = []
        self.failing: set[str] = set()

    @contextmanager
    def patched(self) -> Iterator[None]:
        rooted = test_belt._rooted(self.root)
        with (
            patch("scene.belt.catalog.scene_dir", rooted),
            patch("scene.report.store.scene_dir", rooted),
            patch("scene.belt.run.run_tool", self.run_tool),
            patch("scene.report.run.report_facts", lambda scene_id: FACTS),
            patch("scene.report.run._glossary", lambda: "GLOSSARY TEXT"),
        ):
            yield

    def on_step(self, index: int, sentence: str) -> None:
        self.steps.append((index, sentence))

    def write_measurement(
        self, tool_id: str, partner_id: str | None = None, text: str = "ok"
    ) -> None:
        """What the belt leaves behind for one finished tool."""

        folder = analysis_dir(SCENE, tool_id, partner_id)
        folder.mkdir(parents=True, exist_ok=True)
        payload = {
            "tool_id": tool_id,
            "scene_id": SCENE,
            "partner_id": partner_id,
            "summary": [{"label": f"{tool_id} row", "value": text}],
            "limit": self.limits[tool_id],
        }
        (folder / "measurements.json").write_text(json.dumps(payload), "utf-8")
        (folder / "briefing.md").write_text(f"# {tool_id}\n\nbelt text\n", "utf-8")
        (folder / "overview.png").write_bytes(b"png")

    def run_tool(
        self,
        scene_id: str,
        tool_id: str,
        on_step: Callable[[int, str], None],
        partner_id: str | None = None,
    ) -> None:
        """The fake belt: records the call, reports a step, writes the files."""

        self.ran.append((tool_id, partner_id))
        stored = ReportStore(scene_id).load()
        self.sections_seen_by_run_tool.append(
            [] if stored is None else [item.tool_id for item in stored.sections]
        )
        self.orders_seen.append([] if stored is None else list(stored.tool_order))
        if tool_id in self.failing:
            raise RuntimeError(f"{tool_id} could not run.")
        on_step(1, f"belt step for {tool_id}")
        self.write_measurement(tool_id, partner_id)

    def stored(self) -> dict[str, ReportSection]:
        report = ReportStore(SCENE).load()
        assert report is not None
        return {item.tool_id: item for item in report.sections}

    def report(self) -> Report:
        loaded = ReportStore(SCENE).load()
        assert loaded is not None
        return loaded


class StoreTest(RunnerBase):
    def test_load_is_none_before_a_report_is_saved(self) -> None:
        with self.patched():
            self.assertIsNone(ReportStore(SCENE).load())

    def test_save_then_load_round_trips_the_new_fields(self) -> None:
        section = ReportSection(
            tool_id="open-water",
            status="done",
            measurement={"summary": [], "limit": "x"},
            briefing_md="text",
            briefing_source="model",
            overview_url="/api/scenes/a/analysis/open-water/overview.png",
            partner_id=None,
            progress_note="Measuring open water.",
        )
        report = Report(
            scene_id=SCENE,
            question="",
            partner_id=PARTNER,
            phase="running",
            tool_order=["open-water"],
            synthesis_md="A hedged reading.",
            synthesis_source="model",
            sections=[section],
        )
        with self.patched():
            ReportStore(SCENE).save(report)
            loaded = ReportStore(SCENE).load()
        self.assertEqual(loaded, report)
        path = self.root / "scenes" / SCENE / "report" / "report.json"
        payload = json.loads(path.read_text("utf-8"))
        self.assertEqual(
            set(payload),
            {
                "scene_id",
                "question",
                "partner_id",
                "phase",
                "tool_order",
                "synthesis_md",
                "synthesis_source",
                "sections",
            },
        )
        self.assertEqual(
            set(payload["sections"][0]),
            {
                "tool_id",
                "status",
                "measurement",
                "briefing_md",
                "briefing_source",
                "overview_url",
                "partner_id",
                "progress_note",
            },
        )

    def test_an_older_file_still_loads_and_waiting_is_still_accepted(self) -> None:
        path = self.root / "scenes" / SCENE / "report" / "report.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "scene_id": SCENE,
                    "question": "What is on the water?",
                    "sections": [
                        {
                            "tool_id": "amplitude-change",
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
        with self.patched():
            loaded = ReportStore(SCENE).load()
        assert loaded is not None
        self.assertEqual(loaded.question, "What is on the water?")
        self.assertIsNone(loaded.partner_id)
        self.assertEqual(loaded.phase, "done")
        self.assertEqual(loaded.tool_order, [])
        self.assertEqual(loaded.synthesis_md, "")
        self.assertEqual(loaded.synthesis_source, "belt")
        self.assertEqual(loaded.sections[0].status, "waiting")
        self.assertEqual(loaded.sections[0].progress_note, "")


class RunReportTest(RunnerBase):
    def start(
        self,
        tools: list[IncludedTool],
        chains: FakeChains,
        partner_id: str | None = None,
        matched_dates: int | None = None,
    ) -> None:
        run_report(SCENE, _set(tools, partner_id, matched_dates), chains, self.on_step)

    def test_a_bad_order_falls_back_to_catalog_order_and_the_run_continues(
        self,
    ) -> None:
        tools = [_included("open-water"), _included("sea-roughness")]
        chains = FakeChains()
        chains.order_result = ["sea-roughness"]
        with self.patched():
            self.start(tools, chains)
            report = self.report()
        self.assertEqual(chains.order_calls, [["open-water", "sea-roughness"]])
        self.assertEqual(report.tool_order, ["open-water", "sea-roughness"])
        self.assertEqual(
            self.ran, [("open-water", None), ("sea-roughness", None)]
        )
        self.assertEqual(report.phase, "done")
        self.assertEqual(report.question, "")
        self.assertNotIn("waiting", {item.status for item in report.sections})

    def test_a_failed_order_call_uses_catalog_order(self) -> None:
        chains = FakeChains()
        chains.order_error = RuntimeError("model is down")
        with self.patched():
            self.start([_included("open-water"), _included("sea-roughness")], chains)
            report = self.report()
        self.assertEqual(report.tool_order, ["open-water", "sea-roughness"])
        self.assertEqual(self.ran[0], ("open-water", None))

    def test_a_real_permutation_is_kept(self) -> None:
        chains = FakeChains()
        chains.order_result = ["sea-roughness", "open-water"]
        with self.patched():
            self.start([_included("open-water"), _included("sea-roughness")], chains)
        self.assertEqual(
            self.ran, [("sea-roughness", None), ("open-water", None)]
        )

    def test_the_order_is_on_disk_before_a_tool_runs_and_each_section_is_saved(
        self,
    ) -> None:
        chains = FakeChains()
        with self.patched():
            self.start([_included("open-water"), _included("sea-roughness")], chains)
            sections = self.stored()
        self.assertEqual(chains.phase_during_order, "planning")
        self.assertEqual(self.orders_seen[0], ["open-water", "sea-roughness"])
        self.assertEqual(
            self.sections_seen_by_run_tool[0], ["open-water"]
        )
        self.assertEqual(sections["open-water"].status, "done")
        self.assertEqual(sections["open-water"].briefing_source, "belt")
        self.assertEqual(
            sections["open-water"].briefing_md, "# open-water\n\nbelt text\n"
        )
        self.assertEqual(
            sections["open-water"].progress_note,
            "Measuring Open water on this stripmap scene.",
        )
        self.assertEqual(chains.narrate_calls, [])
        self.assertEqual(
            sections["open-water"].overview_url,
            f"/api/scenes/{SCENE}/analysis/open-water/overview.png",
        )

    def test_progress_notes_stay_plain_when_the_model_would_joke(self) -> None:
        chains = FakeChains()
        chains.note = "The detective referee plays water polo."
        chains.note_error = RuntimeError("narrator is down")
        with self.patched():
            self.start([_included("open-water")], chains)
            section = self.stored()["open-water"]
        self.assertEqual(section.status, "done")
        self.assertEqual(
            section.progress_note, "Measuring Open water on this stripmap scene."
        )
        self.assertEqual(chains.narrate_calls, [])
        text = (self.root / "scenes" / SCENE / "report" / "report.json").read_text(
            "utf-8"
        )
        for banned in ("detective", "referee", "water polo"):
            self.assertNotIn(banned, text.lower())
        self.assertEqual(self.ran, [("open-water", None)])
        self.assertIn((1, section.progress_note), self.steps)
        belt_steps = [
            sentence for _index, sentence in self.steps if "belt step" in sentence
        ]
        self.assertEqual(belt_steps, [])

    def test_a_synthesis_failure_stores_the_belt_compilation(self) -> None:
        chains = FakeChains()
        chains.lead_error = RuntimeError("synthesis is down")
        with self.patched():
            self.start([_included("open-water")], chains)
            report = self.report()
        self.assertEqual(report.synthesis_source, "belt")
        self.assertIn("open-water row", report.synthesis_md)
        self.assertIn("ok", report.synthesis_md)
        self.assertIn(WATER_LIMIT, report.synthesis_md)
        self.assertEqual(report.phase, "done")

    def test_a_stack_run_keeps_the_scope_sentence_when_the_model_omits_it(self) -> None:
        chains = FakeChains()
        chains.lead = "A hedged reading."
        tools = [
            _included("open-water"),
            _included("amplitude-change"),
            _included("water-persistence"),
        ]
        with self.patched():
            self.start(tools, chains, partner_id=PARTNER, matched_dates=2)
            report = self.report()
        self.assertEqual(report.synthesis_source, "model")
        self.assertIn("A hedged reading.", report.synthesis_md)
        self.assertIn(STACK_SCOPE, report.synthesis_md)
        self.assertIn("2 matched dates", report.synthesis_md)
        self.assertEqual(chains.stack_scope, STACK_SCOPE)
        self.assertEqual(report.partner_id, PARTNER)
        self.assertIn(("amplitude-change", PARTNER), self.ran)
        self.assertIn(("water-persistence", None), self.ran)

    def test_no_partner_does_not_add_the_stack_sentence(self) -> None:
        chains = FakeChains()
        with self.patched():
            self.start([_included("open-water")], chains)
            report = self.report()
        self.assertIsNone(chains.stack_scope)
        self.assertEqual(report.synthesis_md, "A hedged reading of the rows.")
        self.assertEqual(report.synthesis_source, "model")
        self.assertNotIn("matched date", report.synthesis_md)

    def test_a_single_scene_lead_that_names_a_stack_or_a_second_date_is_discarded(
        self,
    ) -> None:
        leads = (
            "The comparison uses two dates.",
            "A second date is not in this collect.",
            "This is a short stack.",
            "STACK of returns.",
        )
        for lead in leads:
            with self.subTest(lead=lead):
                chains = FakeChains()
                chains.lead = lead
                with self.patched():
                    self.start([_included("open-water")], chains)
                    report = self.report()
                self.assertEqual(report.synthesis_source, "belt")
                self.assertIn("open-water row", report.synthesis_md)
                lowered = report.synthesis_md.lower()
                self.assertNotIn("two dates", lowered)
                self.assertNotIn("second date", lowered)
                self.assertNotIn("stack", lowered)

    def test_a_grounded_lead_that_names_two_dates_is_kept(self) -> None:
        cases = (
            (PARTNER, None),
            (None, 2),
            (PARTNER, 2),
        )
        for partner_id, matched_dates in cases:
            with self.subTest(partner_id=partner_id, matched_dates=matched_dates):
                chains = FakeChains()
                chains.lead = "Compared across two dates."
                with self.patched():
                    self.start(
                        [_included("open-water")],
                        chains,
                        partner_id=partner_id,
                        matched_dates=matched_dates,
                    )
                    report = self.report()
                self.assertEqual(report.synthesis_source, "model")
                self.assertIn("Compared across two dates.", report.synthesis_md)

    def test_a_locked_tool_is_a_section_and_is_not_run(self) -> None:
        reason = "This collect has no dwell stack."
        chains = FakeChains()
        with self.patched():
            self.start(
                [
                    _included("dwell-motion", locked=True, reason=reason),
                    _included("open-water"),
                ],
                chains,
            )
            sections = self.stored()
        self.assertEqual(sections["dwell-motion"].status, "locked")
        self.assertEqual(sections["dwell-motion"].briefing_md, reason)
        self.assertEqual(self.ran, [("open-water", None)])
        self.assertNotIn("dwell-motion", chains.narrate_calls)

    def test_an_existing_measurement_is_not_run_again(self) -> None:
        chains = FakeChains()
        with self.patched():
            self.write_measurement("open-water")
            self.start([_included("open-water")], chains)
            section = self.stored()["open-water"]
        self.assertEqual(self.ran, [])
        self.assertEqual(chains.narrate_calls, [])
        self.assertEqual(section.status, "done")
        self.assertEqual(
            section.progress_note, "Measuring Open water on this stripmap scene."
        )

    def test_amplitude_reuses_only_the_same_partner_directory(self) -> None:
        tool = _included("amplitude-change")
        chains = FakeChains()
        with self.patched():
            self.write_measurement("amplitude-change", partner_id=None)
            self.start([tool], chains, partner_id=PARTNER)
            self.assertEqual(self.ran, [("amplitude-change", PARTNER)])
            self.ran.clear()
            self.write_measurement("amplitude-change", partner_id=PARTNER)
            self.start([tool], chains, partner_id=PARTNER)
            self.assertEqual(self.ran, [])
            self.start([tool], chains, partner_id=OTHER)
            self.assertEqual(self.ran, [("amplitude-change", OTHER)])

    def test_a_tool_that_fails_is_marked_failed_and_the_rest_still_run(self) -> None:
        self.failing = {"open-water"}
        chains = FakeChains()
        with self.patched():
            self.start([_included("open-water"), _included("sea-roughness")], chains)
            sections = self.stored()
        self.assertEqual(sections["open-water"].status, "failed")
        self.assertIn("open-water could not run.", sections["open-water"].briefing_md)
        self.assertEqual(
            sections["open-water"].progress_note,
            "Measuring Open water on this stripmap scene.",
        )
        self.assertEqual(
            sections["sea-roughness"].progress_note,
            "Measuring Sea roughness on this stripmap scene.",
        )
        self.assertEqual(sections["sea-roughness"].status, "done")
        self.assertEqual(chains.narrate_calls, [])

    def test_a_running_section_is_visible_while_its_tool_runs(self) -> None:
        seen: list[str] = []
        notes: list[str] = []
        original = self.run_tool

        def watching(
            scene_id: str,
            tool_id: str,
            on_step: Callable[[int, str], None],
            partner_id: str | None = None,
        ) -> None:
            report = ReportStore(scene_id).load()
            assert report is not None
            match = [item for item in report.sections if item.tool_id == tool_id]
            seen.extend(item.status for item in match)
            notes.extend(item.progress_note for item in match)
            original(scene_id, tool_id, on_step, partner_id)

        rooted = test_belt._rooted(self.root)
        with (
            patch("scene.belt.catalog.scene_dir", rooted),
            patch("scene.report.store.scene_dir", rooted),
            patch("scene.belt.run.run_tool", watching),
            patch("scene.report.run.report_facts", lambda scene_id: FACTS),
            patch("scene.report.run._glossary", lambda: "GLOSSARY TEXT"),
        ):
            chains = FakeChains()
            chains.note = "The detective referee plays water polo."
            self.start([_included("open-water")], chains)
        self.assertEqual(seen, ["running"])
        self.assertEqual(notes, ["Measuring Open water on this stripmap scene."])
        self.assertEqual(chains.narrate_calls, [])


class StartReportTest(unittest.TestCase):
    def test_a_second_start_while_running_raises(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def runner(on_step: Callable[[int, str], None]) -> None:
            on_step(1, "Working.")
            started.set()
            release.wait(timeout=2)

        with tempfile.TemporaryDirectory() as tmp:
            manager = MeasurementJobManager(output_dir=Path(tmp))
            manager.start_report(runner)
            self.assertTrue(started.wait(timeout=2))
            with self.assertRaises(JobAlreadyRunningError):
                manager.start_report(runner)
            self.assertEqual(manager.current().status, "running")
            self.assertEqual(manager.current().sentence, "Working.")
            release.set()
            thread = manager._thread
            assert thread is not None
            thread.join(timeout=2)
            self.assertEqual(manager.current().status, "done")

    def test_a_finished_report_job_has_no_result_and_keeps_its_sentence(self) -> None:
        """Belt panes treat any done result as tool output, so a report has none."""

        def runner(on_step: Callable[[int, str], None]) -> None:
            on_step(2, "Writing the report.")

        with tempfile.TemporaryDirectory() as tmp:
            manager = MeasurementJobManager(output_dir=Path(tmp))
            manager.start_report(runner)
            thread = manager._thread
            assert thread is not None
            thread.join(timeout=2)
            snapshot = manager.current()
        self.assertEqual(snapshot.status, "done")
        self.assertIsNone(snapshot.result)
        self.assertIsNone(snapshot.to_public()["result"])
        self.assertEqual(snapshot.sentence, "Writing the report.")

    def test_the_lisbon_start_still_publishes_its_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "measurements.json").write_text('{"summary": []}', "utf-8")
            manager = MeasurementJobManager(runner=lambda on_step: None, output_dir=out)
            manager.start()
            thread = manager._thread
            assert thread is not None
            thread.join(timeout=2)
            result = manager.current().result
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.measurement, {"summary": []})

    def test_a_runner_error_becomes_the_job_error(self) -> None:
        def runner(on_step: Callable[[int, str], None]) -> None:
            raise RuntimeError("The report could not start.")

        with tempfile.TemporaryDirectory() as tmp:
            manager = MeasurementJobManager(output_dir=Path(tmp))
            manager.start_report(runner)
            thread = manager._thread
            assert thread is not None
            thread.join(timeout=2)
            snapshot = manager.current()
        self.assertEqual(snapshot.status, "failed")
        self.assertEqual(snapshot.error, "The report could not start.")


if __name__ == "__main__":
    unittest.main()
