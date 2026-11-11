"""Store and run: the report is written section by section, one tool at a time."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scene.belt.catalog import analysis_dir
from scene.jobs import JobAlreadyRunningError, MeasurementJobManager
from scene.report.run import run_amplitude, run_report
from scene.report.schema import LockedTool, ReportPlan
from scene.report.store import ReportSection, ReportStore
from tests import test_belt

SCENE = "ICEYE_A_20260211T000000Z_1_X1_SM"
PARTNER = "ICEYE_B_20260212T000000Z_1_X1_SM"
QUESTION = "What is on the water?"

WATER_LIMIT = "Shadow, tarmac, and sand are dark for the same reason."
ROUGH_LIMIT = "This split is roughness, not a wave height."
CHANGE_LIMIT = "The picture is a shared stretch."
FACTS = object()

Steps = list[tuple[int, str]]


class FakeChains:
    """A stand-in for ReportChains. It records every phrase call."""

    def __init__(self, reply: Callable[[Mapping[str, object]], str]) -> None:
        self._reply = reply
        self.calls: list[tuple[str, object, Mapping[str, object]]] = []

    def phrase(
        self, question: str, facts: object, measurement: Mapping[str, object]
    ) -> str:
        self.calls.append((question, facts, measurement))
        return self._reply(measurement)


def _echo_limit(measurement: Mapping[str, object]) -> str:
    """Model prose that keeps the limit string unchanged."""

    return f"In plain words. {measurement['limit']}"


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
        }
        self.sections_seen_by_run_tool: list[list[str]] = []
        self.failing: set[str] = set()

    @contextmanager
    def patched(self) -> Iterator[None]:
        rooted = test_belt._rooted(self.root)
        with (
            patch("scene.belt.catalog.scene_dir", rooted),
            patch("scene.report.store.scene_dir", rooted),
            patch("scene.belt.run.run_tool", self.run_tool),
            patch("scene.report.run.report_facts", lambda scene_id: FACTS),
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
        if tool_id in self.failing:
            raise RuntimeError(f"{tool_id} could not run.")
        on_step(1, f"belt step for {tool_id}")
        self.write_measurement(tool_id, partner_id)

    def plan(self, **changes: Any) -> ReportPlan:
        base: dict[str, Any] = {
            "selected": ["open-water", "sea-roughness"],
            "waiting": [],
            "locked": [],
        }
        base.update(changes)
        return ReportPlan(**base)

    def stored(self) -> dict[str, ReportSection]:
        report = ReportStore(SCENE).load()
        assert report is not None
        return {item.tool_id: item for item in report.sections}


class StoreTest(RunnerBase):
    def test_load_is_none_before_a_report_is_saved(self) -> None:
        with self.patched():
            self.assertIsNone(ReportStore(SCENE).load())

    def test_save_then_load_round_trips_at_the_report_path(self) -> None:
        section = ReportSection(
            tool_id="open-water",
            status="done",
            measurement={"summary": [], "limit": "x"},
            briefing_md="text",
            briefing_source="model",
            overview_url="/api/scenes/a/analysis/open-water/overview.png",
            partner_id=None,
        )
        with self.patched():
            store = ReportStore(SCENE)
            store.save(store.new(QUESTION, [section]))
            loaded = store.load()
        assert loaded is not None
        self.assertEqual(loaded.question, QUESTION)
        self.assertEqual(loaded.sections, [section])
        path = self.root / "scenes" / SCENE / "report" / "report.json"
        self.assertTrue(path.is_file())
        keys = set(json.loads(path.read_text("utf-8"))["sections"][0])
        self.assertEqual(
            keys,
            {
                "tool_id",
                "status",
                "measurement",
                "briefing_md",
                "briefing_source",
                "overview_url",
                "partner_id",
            },
        )


class RunReportTest(RunnerBase):
    def run_report(self, plan: ReportPlan, chains: FakeChains) -> None:
        run_report(SCENE, QUESTION, plan, chains, self.on_step)

    def test_locked_and_waiting_sections_are_written_before_any_tool_runs(
        self,
    ) -> None:
        plan = self.plan(
            selected=["open-water"],
            waiting=["amplitude-change"],
            locked=[LockedTool("dwell-motion", "This collect has no dwell stack.")],
        )
        chains = FakeChains(_echo_limit)
        with self.patched():
            self.run_report(plan, chains)
            sections = self.stored()
        # The fixed sections are on disk first, then the running tool's own.
        self.assertEqual(
            self.sections_seen_by_run_tool[0],
            ["dwell-motion", "amplitude-change", "open-water"],
        )
        locked = sections["dwell-motion"]
        self.assertEqual(locked.status, "locked")
        self.assertEqual(locked.briefing_md, "This collect has no dwell stack.")
        self.assertEqual(locked.briefing_source, "belt")
        self.assertIsNone(locked.overview_url)
        self.assertIsNone(locked.measurement)
        waiting = sections["amplitude-change"]
        self.assertEqual(waiting.status, "waiting")
        self.assertIsNone(waiting.partner_id)
        self.assertEqual(waiting.briefing_md, "The comparison has not been made.")
        self.assertNotIn(("amplitude-change", None), self.ran)
        self.assertEqual(self.ran, [("open-water", None)])

    def test_the_tools_run_in_plan_order_and_each_is_phrased_alone(self) -> None:
        chains = FakeChains(_echo_limit)
        with self.patched():
            self.run_report(self.plan(), chains)
            sections = self.stored()
        self.assertEqual(self.ran, [("open-water", None), ("sea-roughness", None)])
        self.assertEqual(len(chains.calls), 2)
        for (question, facts, measurement), tool_id in zip(
            chains.calls, ["open-water", "sea-roughness"], strict=True
        ):
            self.assertEqual(question, QUESTION)
            self.assertIs(facts, FACTS)
            self.assertEqual(measurement["tool_id"], tool_id)
            self.assertEqual(
                [row["label"] for row in measurement["summary"]],  # type: ignore[attr-defined]
                [f"{tool_id} row"],
            )
        self.assertEqual(list(sections), ["open-water", "sea-roughness"])
        done = sections["open-water"]
        self.assertEqual(done.status, "done")
        self.assertEqual(done.briefing_source, "model")
        self.assertIn(WATER_LIMIT, done.briefing_md)
        self.assertEqual(
            done.overview_url,
            f"/api/scenes/{SCENE}/analysis/open-water/overview.png",
        )

    def test_the_second_phrase_call_does_not_see_the_first_tools_summary(self) -> None:
        chains = FakeChains(_echo_limit)
        with self.patched():
            self.run_report(self.plan(), chains)
        first = json.dumps(chains.calls[0][2])
        second = json.dumps(chains.calls[1][2])
        self.assertNotIn("sea-roughness", first)
        self.assertNotIn("open-water", second)

    def test_an_existing_measurement_is_not_run_again(self) -> None:
        chains = FakeChains(_echo_limit)
        with self.patched():
            self.write_measurement("open-water")
            self.run_report(self.plan(selected=["open-water"]), chains)
            sections = self.stored()
        self.assertEqual(self.ran, [])
        self.assertEqual(len(chains.calls), 1)
        self.assertEqual(sections["open-water"].status, "done")
        self.assertEqual(len(self.steps), 1)
        sentence = self.steps[0][1]
        self.assertIn("Open water", sentence)
        self.assertIn("already on disk", sentence)

    def test_a_tool_that_runs_passes_the_belt_step_callback_through(self) -> None:
        with self.patched():
            self.run_report(self.plan(selected=["open-water"]), FakeChains(_echo_limit))
        self.assertEqual(self.steps, [(1, "belt step for open-water")])

    def test_text_without_the_limit_string_stores_the_belt_briefing(self) -> None:
        chains = FakeChains(lambda _measurement: "A tidy paragraph with no limit.")
        with self.patched():
            self.run_report(self.plan(selected=["open-water"]), chains)
            section = self.stored()["open-water"]
        self.assertEqual(section.briefing_source, "belt")
        self.assertEqual(section.status, "done")
        self.assertEqual(section.briefing_md, "# open-water\n\nbelt text\n")

    def test_a_limit_string_that_was_reworded_stores_the_belt_briefing(self) -> None:
        chains = FakeChains(lambda _measurement: WATER_LIMIT.lower())
        with self.patched():
            self.run_report(self.plan(selected=["open-water"]), chains)
            section = self.stored()["open-water"]
        self.assertEqual(section.briefing_source, "belt")

    def test_a_chain_error_keeps_the_belt_briefing(self) -> None:
        def boom(_measurement: Mapping[str, object]) -> str:
            raise RuntimeError("model is down")

        with self.patched():
            self.run_report(self.plan(selected=["open-water"]), FakeChains(boom))
            section = self.stored()["open-water"]
        self.assertEqual(section.briefing_source, "belt")
        self.assertEqual(section.status, "done")
        self.assertEqual(section.briefing_md, "# open-water\n\nbelt text\n")

    def test_a_tool_that_fails_is_marked_failed_and_the_rest_still_run(self) -> None:
        self.failing = {"open-water"}
        chains = FakeChains(_echo_limit)
        with self.patched():
            self.run_report(self.plan(), chains)
            sections = self.stored()
        self.assertEqual(sections["open-water"].status, "failed")
        self.assertIn("open-water could not run.", sections["open-water"].briefing_md)
        self.assertEqual(sections["open-water"].briefing_source, "belt")
        self.assertEqual(sections["sea-roughness"].status, "done")
        self.assertEqual(len(chains.calls), 1)

    def test_a_running_section_is_visible_while_its_tool_runs(self) -> None:
        seen: list[str] = []
        original = self.run_tool

        def watching(
            scene_id: str,
            tool_id: str,
            on_step: Callable[[int, str], None],
            partner_id: str | None = None,
        ) -> None:
            report = ReportStore(scene_id).load()
            assert report is not None
            seen.extend(
                item.status for item in report.sections if item.tool_id == tool_id
            )
            original(scene_id, tool_id, on_step, partner_id)

        rooted = test_belt._rooted(self.root)
        with (
            patch("scene.belt.catalog.scene_dir", rooted),
            patch("scene.report.store.scene_dir", rooted),
            patch("scene.belt.run.run_tool", watching),
            patch("scene.report.run.report_facts", lambda scene_id: FACTS),
        ):
            self.run_report(self.plan(selected=["open-water"]), FakeChains(_echo_limit))
        self.assertEqual(seen, ["running"])


class RunAmplitudeTest(RunnerBase):
    def test_only_amplitude_change_runs_and_only_its_section_is_replaced(
        self,
    ) -> None:
        plan = self.plan(
            selected=["open-water"],
            waiting=["amplitude-change"],
            locked=[LockedTool("dwell-motion", "No dwell stack.")],
        )
        first = FakeChains(_echo_limit)
        second = FakeChains(_echo_limit)
        with self.patched():
            run_report(SCENE, QUESTION, plan, first, self.on_step)
            before = self.stored()
            self.ran.clear()
            self.steps.clear()
            run_amplitude(SCENE, PARTNER, second, self.on_step)
            after = self.stored()
        self.assertEqual(self.ran, [("amplitude-change", PARTNER)])
        self.assertEqual(self.steps, [(1, "belt step for amplitude-change")])
        self.assertEqual(len(second.calls), 1)
        measurement = second.calls[0][2]
        self.assertEqual(measurement["tool_id"], "amplitude-change")
        self.assertNotIn("open-water", json.dumps(measurement))
        self.assertEqual(after["open-water"], before["open-water"])
        self.assertEqual(after["dwell-motion"], before["dwell-motion"])
        change = after["amplitude-change"]
        self.assertEqual(change.status, "done")
        self.assertEqual(change.partner_id, PARTNER)
        self.assertEqual(change.briefing_source, "model")
        self.assertIn(CHANGE_LIMIT, change.briefing_md)
        self.assertEqual(
            change.overview_url,
            f"/api/scenes/{SCENE}/analysis/amplitude-change/{PARTNER}/overview.png",
        )
        self.assertEqual(list(after), list(before))

    def test_a_missing_limit_string_keeps_the_belt_briefing(self) -> None:
        plan = self.plan(selected=[], waiting=["amplitude-change"])
        with self.patched():
            run_report(SCENE, QUESTION, plan, FakeChains(_echo_limit), self.on_step)
            run_amplitude(
                SCENE, PARTNER, FakeChains(lambda _m: "No limit here."), self.on_step
            )
            change = self.stored()["amplitude-change"]
        self.assertEqual(change.briefing_source, "belt")
        self.assertEqual(change.status, "done")
        self.assertEqual(change.briefing_md, "# amplitude-change\n\nbelt text\n")

    def test_it_adds_the_section_when_the_report_had_none(self) -> None:
        with self.patched():
            run_report(
                SCENE,
                QUESTION,
                self.plan(selected=["open-water"]),
                FakeChains(_echo_limit),
                self.on_step,
            )
            run_amplitude(SCENE, PARTNER, FakeChains(_echo_limit), self.on_step)
            sections = self.stored()
        self.assertEqual(list(sections), ["open-water", "amplitude-change"])


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
