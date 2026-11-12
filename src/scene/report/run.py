"""Build the report: order the tools, run each one, then write one lead.

The belt measures. A model call that fails does not stop the run: the tool
order falls back to the belt catalog, each step stores a plain progress
sentence, and a synthesis failure becomes a lead built from the summary rows.
A single-scene lead that invents a second date or a stack is discarded too.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Literal, Protocol

from scene.belt import run as belt_run
from scene.belt.catalog import analysis_dir
from scene.paths import project_root
from scene.report.facts import ReportFacts, report_facts
from scene.report.select import (
    AMPLITUDE_TOOL,
    STACK_SCOPE,
    IncludedTool,
    ToolSet,
)
from scene.report.store import BriefingSource, Report, ReportSection, ReportStore

OnStep = Callable[[int, str], None]

LOCKED_FALLBACK = "The belt keeps this tool locked for this scene."


class ReportModel(Protocol):
    """The part of ``ReportChains`` the run needs. Tests give it a fake."""

    def order(
        self, facts: ReportFacts, tools: Sequence[Mapping[str, str]]
    ) -> list[str]: ...

    def narrate(self, facts: ReportFacts, tool: Mapping[str, str]) -> str: ...

    def synthesize(
        self,
        facts: ReportFacts,
        partner_id: str | None,
        sections: Sequence[ReportSection],
        glossary: str,
        *,
        stack_scope: str | None,
        matched_dates: int | None,
    ) -> str: ...


class FallbackModel:
    """Every call fails. The run keeps the catalog, a plain note, and the belt lead."""

    def order(
        self, facts: ReportFacts, tools: Sequence[Mapping[str, str]]
    ) -> list[str]:
        raise RuntimeError("No model is configured.")

    def narrate(self, facts: ReportFacts, tool: Mapping[str, str]) -> str:
        raise RuntimeError("No model is configured.")

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
        raise RuntimeError("No model is configured.")


def run_report(
    scene_id: str,
    chosen: ToolSet,
    chains: ReportModel,
    on_step: OnStep,
) -> None:
    """Write the report for ``chosen``, saving at each phase the page polls.

    The file is written while the order is being chosen, again when that order
    is known, after every section, while the lead is written, and after it.
    A tool that raises becomes a failed section and the next tool still runs.
    """

    facts = report_facts(scene_id)
    glossary = _glossary()
    store = ReportStore(scene_id)
    report = Report(
        scene_id=scene_id,
        question="",
        partner_id=chosen.partner_id,
        phase="planning",
        tool_order=[],
        synthesis_md="",
        synthesis_source="belt",
        sections=[],
    )
    store.save(report)
    report = replace(
        report,
        phase="running",
        tool_order=_ordered(chains, facts, chosen),
        sections=_locked_sections(chosen),
    )
    store.save(report)
    by_id = {tool.id: tool for tool in chosen.tools}
    for tool_id in report.tool_order:
        report = _build_section(
            scene_id,
            by_id[tool_id],
            chosen.partner_id,
            facts,
            chains,
            on_step,
            store,
            report,
        )
    report = replace(report, phase="writing")
    store.save(report)
    text, source = _synthesize(chains, facts, chosen, report.sections, glossary)
    store.save(
        replace(report, phase="done", synthesis_md=text, synthesis_source=source)
    )


def belt_lead(
    facts: ReportFacts, chosen: ToolSet, sections: Sequence[ReportSection]
) -> str:
    """A lead made only from the rows, the limits, the failures, and the locks.

    Nothing here is inferred. A stack run also states that every matched date
    was compared, and how many dates that was.
    """

    labels = {tool.id: tool.label for tool in chosen.tools}
    parts: list[str] = []
    if chosen.partner_id:
        parts.append(f"Partner scene: {chosen.partner_id}.")
    if chosen.matched_dates is not None:
        parts.append(
            f"{STACK_SCOPE} This comparison uses {chosen.matched_dates} matched dates."
        )
    for section in sections:
        label = labels.get(section.tool_id, section.tool_id)
        if section.status == "locked":
            parts.append(f"{label} is locked. {section.briefing_md}".strip())
            continue
        if section.status == "failed":
            parts.append(f"{label} failed. {section.briefing_md}".strip())
            continue
        if section.status != "done" or section.measurement is None:
            continue
        summary = section.measurement.get("summary")
        if isinstance(summary, list):
            for row in summary:
                if isinstance(row, dict):
                    parts.append(
                        f"{label}: {row.get('label', '')}: {row.get('value', '')}."
                    )
        limit = section.measurement.get("limit")
        if isinstance(limit, str) and limit:
            parts.append(limit)
    if not parts:
        mode = facts.mode or "this"
        parts.append(f"No measurement was stored for this {mode} scene.")
    return "\n\n".join(parts)


def _ordered(chains: ReportModel, facts: ReportFacts, chosen: ToolSet) -> list[str]:
    """The model's permutation, or the belt catalog order when the reply is unusable."""

    runnable = [tool for tool in chosen.tools if not tool.locked]
    expected = [tool.id for tool in runnable]
    payload = [
        {"id": tool.id, "label": tool.label, "description": tool.description}
        for tool in runnable
    ]
    try:
        proposed = chains.order(facts, payload)
    except Exception:  # noqa: BLE001 - a failed order call keeps the catalog order.
        return expected
    if _permutation(proposed, expected):
        return proposed
    return expected


def _permutation(proposed: Sequence[str], expected: Sequence[str]) -> bool:
    """True when ``proposed`` is exactly the ids in ``expected``, in any order."""

    return len(proposed) == len(expected) and set(proposed) == set(expected)


def _build_section(
    scene_id: str,
    tool: IncludedTool,
    partner_id: str | None,
    facts: ReportFacts,
    chains: ReportModel,
    on_step: OnStep,
    store: ReportStore,
    report: Report,
) -> Report:
    """Narrate, measure or reuse, and save. A tool error is only this section."""

    partner = partner_id if tool.id == AMPLITUDE_TOOL else None
    note = _narrate(chains, facts, tool)
    report = _save(store, report, _unfinished(tool.id, "running", partner, note))
    # The poll reads this sentence while the raster runs. Belt steps do not replace it.
    on_step(1, note)

    folder = analysis_dir(scene_id, tool.id, partner)
    try:
        if not (folder / "measurements.json").is_file():
            belt_run.run_tool(scene_id, tool.id, _hold(note, on_step), partner)
        measurement = _read_measurement(folder)
        belt_text = (folder / "briefing.md").read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - a tool failure becomes its section.
        failed = _unfinished(tool.id, "failed", partner, note, _reason(exc))
        return _save(store, report, failed)
    section = ReportSection(
        tool_id=tool.id,
        status="done",
        measurement=measurement,
        briefing_md=belt_text,
        briefing_source="belt",
        overview_url=_overview_url(scene_id, tool.id, partner, folder),
        partner_id=partner,
        progress_note=note,
    )
    return _save(store, report, section)


def _narrate(chains: ReportModel, facts: ReportFacts, tool: IncludedTool) -> str:
    """One plain progress sentence. The model is not asked to write this line."""

    del chains
    return _plain_note(tool.label, facts.mode)


def _plain_note(label: str, mode: str) -> str:
    """The progress sentence for one tool. The model does not write it."""

    scene_mode = mode or "radar"
    return f"Measuring {label} on this {scene_mode} scene."


def _synthesize(
    chains: ReportModel,
    facts: ReportFacts,
    chosen: ToolSet,
    sections: Sequence[ReportSection],
    glossary: str,
) -> tuple[str, BriefingSource]:
    """The model's lead, or the belt compilation when that reply cannot be kept.

    A blank or failed call uses the belt compilation. So does a single-scene
    reply that mentions a second date or a stack. A stack run keeps the scope
    sentence even when the model omits it.
    """

    scope = STACK_SCOPE if chosen.matched_dates is not None else None
    try:
        text = chains.synthesize(
            facts,
            chosen.partner_id,
            sections,
            glossary,
            stack_scope=scope,
            matched_dates=chosen.matched_dates,
        )
    except Exception:  # noqa: BLE001 - a failed lead keeps the belt compilation.
        return belt_lead(facts, chosen, sections), "belt"
    cleaned = text.strip()
    if not cleaned or _ungrounded_lead(cleaned, chosen):
        return belt_lead(facts, chosen, sections), "belt"
    return _with_stack_scope(cleaned, chosen), "model"


def _ungrounded_lead(text: str, chosen: ToolSet) -> bool:
    """True when a single scene's lead invents a second date or a stack.

    A partner, or a matched-date count, is the only ground for those words.
    """

    if chosen.matched_dates is not None or chosen.partner_id is not None:
        return False
    return (
        re.search(r"two dates|second date|stack", text, re.IGNORECASE) is not None
    )


def _with_stack_scope(text: str, chosen: ToolSet) -> str:
    """Append the stack sentence when this run compared every matched date."""

    if chosen.matched_dates is None or STACK_SCOPE in text:
        return text
    extra = (
        f"{STACK_SCOPE} This comparison uses {chosen.matched_dates} matched dates."
    )
    return f"{text.rstrip()}\n\n{extra}"


def _locked_sections(chosen: ToolSet) -> list[ReportSection]:
    """Locked tools in this set, with the belt's sentence. They are not run."""

    return [
        ReportSection(
            tool_id=tool.id,
            status="locked",
            measurement=None,
            briefing_md=tool.reason or LOCKED_FALLBACK,
            briefing_source="belt",
            overview_url=None,
            partner_id=None,
            progress_note="",
        )
        for tool in chosen.tools
        if tool.locked
    ]


def _hold(note: str, on_step: OnStep) -> OnStep:
    """A step callback that keeps the narrator line as the job sentence."""

    def forward(_index: int, _sentence: str) -> None:
        on_step(1, note)

    return forward


def _unfinished(
    tool_id: str,
    status: Literal["running", "failed"],
    partner_id: str | None,
    progress_note: str,
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
        progress_note=progress_note,
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


def _glossary() -> str:
    """The only extra text synthesis may use. A missing file yields nothing."""

    path = project_root() / "content" / "sar_glossary.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _reason(exc: Exception) -> str:
    """One line a person can read."""

    text = str(exc).strip() or exc.__class__.__name__
    return " ".join(text.split())[:500]
