"""Build the report: run each chosen tool once, then phrase that tool alone."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal, Protocol

from scene.belt import run as belt_run
from scene.belt.catalog import analysis_dir, tool_spec
from scene.report.facts import ReportFacts, report_facts
from scene.report.schema import ReportPlan
from scene.report.store import BriefingSource, Report, ReportSection, ReportStore

OnStep = Callable[[int, str], None]

# The one tool that needs a second scene. The report only waits for it.
AMPLITUDE_TOOL = "amplitude-change"
WAITING_BRIEFING = "The comparison has not been made."
LOCKED_FALLBACK = "The belt keeps this tool locked for this scene."


class Phraser(Protocol):
    """The part of ``ReportChains`` the run needs. Tests give it a fake."""

    def phrase(
        self, question: str, facts: ReportFacts, measurement: Mapping[str, object]
    ) -> str: ...


def run_report(
    scene_id: str,
    question: str,
    plan: ReportPlan,
    chains: Phraser,
    on_step: OnStep,
) -> None:
    """Write the report for ``plan``, saving after every section.

    Locked and waiting sections go first, so the page has something to show.
    Each selected tool then runs only when its ``measurements.json`` is missing,
    and is phrased from its own measurement alone. A tool that fails becomes a
    ``failed`` section with the reason, and the next tool still runs.
    """

    store = ReportStore(scene_id)
    report = store.new(question, _fixed_sections(plan))
    store.save(report)
    facts = report_facts(scene_id)
    for tool_id in plan.selected:
        report = _build_section(
            scene_id, question, tool_id, None, facts, chains, on_step, store, report
        )


def run_amplitude(
    scene_id: str,
    partner_id: str,
    chains: Phraser,
    on_step: OnStep,
) -> None:
    """Run amplitude change against ``partner_id`` and replace only that section.

    The other sections and their phrasing are left exactly as saved.
    """

    store = ReportStore(scene_id)
    report = store.load()
    if report is None:
        raise RuntimeError(
            "There is no report for this scene to add the comparison to."
        )
    facts = report_facts(scene_id)
    _build_section(
        scene_id,
        report.question,
        AMPLITUDE_TOOL,
        partner_id,
        facts,
        chains,
        on_step,
        store,
        report,
        always_run=True,
    )


def _fixed_sections(plan: ReportPlan) -> list[ReportSection]:
    """Locked tools, then amplitude change when it waits. No tool has run."""

    sections = [
        ReportSection(
            tool_id=locked.id,
            status="locked",
            measurement=None,
            briefing_md=locked.reason or LOCKED_FALLBACK,
            briefing_source="belt",
            overview_url=None,
            partner_id=None,
        )
        for locked in plan.locked
    ]
    if AMPLITUDE_TOOL in plan.waiting:
        sections.append(
            ReportSection(
                tool_id=AMPLITUDE_TOOL,
                status="waiting",
                measurement=None,
                briefing_md=WAITING_BRIEFING,
                briefing_source="belt",
                overview_url=None,
                partner_id=None,
            )
        )
    return sections


def _build_section(
    scene_id: str,
    question: str,
    tool_id: str,
    partner_id: str | None,
    facts: ReportFacts,
    chains: Phraser,
    on_step: OnStep,
    store: ReportStore,
    report: Report,
    always_run: bool = False,
) -> Report:
    """Run one tool if needed, phrase it, and save the report with its section."""

    report = _save(store, report, _unfinished(tool_id, "running", partner_id))
    folder = analysis_dir(scene_id, tool_id, partner_id)
    try:
        if always_run or not (folder / "measurements.json").is_file():
            belt_run.run_tool(scene_id, tool_id, on_step, partner_id)
        else:
            on_step(
                1,
                f"{tool_spec(tool_id).label}: the measurement is already on disk.",
            )
        measurement = _read_measurement(folder)
        belt_text = (folder / "briefing.md").read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - a tool failure becomes its section.
        failed = _unfinished(tool_id, "failed", partner_id, _reason(exc))
        return _save(store, report, failed)
    text, source = _phrase(chains, question, facts, measurement, belt_text)
    section = ReportSection(
        tool_id=tool_id,
        status="done",
        measurement=measurement,
        briefing_md=text,
        briefing_source=source,
        overview_url=_overview_url(scene_id, tool_id, partner_id, folder),
        partner_id=partner_id,
    )
    return _save(store, report, section)


def _phrase(
    chains: Phraser,
    question: str,
    facts: ReportFacts,
    measurement: dict[str, object],
    belt_text: str,
) -> tuple[str, BriefingSource]:
    """The model's text when it keeps the limit unchanged. Else the belt's.

    A chain error or a phrase that drops the limit string is not an error for
    the report: the belt's own briefing.md says the same thing and keeps the
    limit, so it is stored instead.
    """

    limit = measurement.get("limit")
    try:
        text = chains.phrase(question, facts, measurement)
    except Exception:  # noqa: BLE001 - any chain failure keeps the belt briefing.
        return belt_text, "belt"
    if isinstance(limit, str) and limit and limit in text:
        return text, "model"
    return belt_text, "belt"


def _unfinished(
    tool_id: str,
    status: Literal["running", "failed"],
    partner_id: str | None,
    briefing_md: str = "",
) -> ReportSection:
    """A section with no measurement yet: ``running`` or ``failed``."""

    return ReportSection(
        tool_id=tool_id,
        status=status,
        measurement=None,
        briefing_md=briefing_md,
        briefing_source="belt",
        overview_url=None,
        partner_id=partner_id,
    )


def _save(store: ReportStore, report: Report, section: ReportSection) -> Report:
    """Put ``section`` in the report, write it, and return the new report."""

    updated = report.with_section(section)
    store.save(updated)
    return updated


def _read_measurement(folder: Path) -> dict[str, object]:
    """The belt's measurements.json. Anything but an object is an error."""

    payload = json.loads((folder / "measurements.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("measurements.json is not a JSON object")
    return payload


def _overview_url(
    scene_id: str, tool_id: str, partner_id: str | None, folder: Path
) -> str | None:
    """The belt's picture URL, or None when the tool drew none."""

    if not (folder / "overview.png").is_file():
        return None
    base = f"/api/scenes/{scene_id}/analysis/{tool_id}"
    if partner_id:
        return f"{base}/{partner_id}/overview.png"
    return f"{base}/overview.png"


def _reason(exc: Exception) -> str:
    """One line a person can read."""

    text = str(exc).strip() or exc.__class__.__name__
    return " ".join(text.split())[:500]
