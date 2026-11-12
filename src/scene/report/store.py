"""The saved report: one JSON file per scene, one section per tool."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Literal

from scene.paths import scene_dir

SectionStatus = Literal["done", "waiting", "locked", "running", "failed"]
BriefingSource = Literal["model", "belt"]
Phase = Literal["planning", "running", "writing", "done"]


@dataclass(frozen=True)
class ReportSection:
    """What the report says about one tool."""

    tool_id: str
    status: SectionStatus
    # The belt's measurements.json (``summary`` and ``limit``). None until it ran.
    measurement: dict[str, object] | None
    briefing_md: str
    # ``belt`` for a lock, a failure, or the tool's own briefing.md.
    briefing_source: BriefingSource
    overview_url: str | None
    # The second scene of an amplitude change. None for every other tool.
    partner_id: str | None
    # The narrator line shown while this tool runs. Empty once that was not saved.
    progress_note: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> ReportSection:
        """Read one section back. A missing new key keeps a default.

        ``waiting`` is still accepted so a report saved by the older page loads.
        A new run does not write that status.
        """

        measurement = raw["measurement"]
        overview_url = raw["overview_url"]
        partner_id = raw["partner_id"]
        return cls(
            tool_id=str(raw["tool_id"]),
            status=_status(raw["status"]),
            measurement=measurement if isinstance(measurement, dict) else None,
            briefing_md=str(raw["briefing_md"]),
            briefing_source=_source(raw["briefing_source"]),
            overview_url=overview_url if isinstance(overview_url, str) else None,
            partner_id=partner_id if isinstance(partner_id, str) else None,
            progress_note=str(raw.get("progress_note", "")),
        )


@dataclass(frozen=True)
class Report:
    """One scene report. ``question`` stays in the file and is empty for a new run."""

    scene_id: str
    question: str
    partner_id: str | None = None
    phase: Phase = "done"
    tool_order: list[str] = field(default_factory=list)
    synthesis_md: str = ""
    synthesis_source: BriefingSource = "belt"
    sections: list[ReportSection] = field(default_factory=list)

    def with_section(self, section: ReportSection) -> Report:
        """Replace the section for the same tool, or append when it is new.

        Every other section is kept exactly as it is.
        """

        sections = list(self.sections)
        for index, existing in enumerate(sections):
            if existing.tool_id == section.tool_id:
                sections[index] = section
                break
        else:
            sections.append(section)
        return replace(self, sections=sections)


class ReportStore:
    """Read and write ``data/scenes/<id>/report/report.json``."""

    def __init__(self, scene_id: str) -> None:
        self._scene_id = scene_id

    @property
    def path(self) -> Path:
        return scene_dir(self._scene_id) / "report" / "report.json"

    def new(self, sections: list[ReportSection] | None = None) -> Report:
        """An empty-question report for this scene, before anything is saved."""

        return Report(
            scene_id=self._scene_id,
            question="",
            sections=list(sections or []),
        )

    def load(self) -> Report | None:
        """The saved report, or None when this scene has none.

        Keys added after the first report format default, so an older file
        still loads. A present key of the wrong shape is an error.
        """

        if not self.path.is_file():
            return None
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("report.json is not a JSON object")
        sections = raw["sections"]
        if not isinstance(sections, list):
            raise ValueError("sections is not a list")
        return Report(
            scene_id=str(raw["scene_id"]),
            question=str(raw["question"]) if "question" in raw else "",
            partner_id=_optional_str(raw, "partner_id"),
            phase=_phase(raw["phase"]) if "phase" in raw else "done",
            tool_order=_str_list(raw, "tool_order"),
            synthesis_md=str(raw["synthesis_md"]) if "synthesis_md" in raw else "",
            synthesis_source=(
                _source(raw["synthesis_source"])
                if "synthesis_source" in raw
                else "belt"
            ),
            sections=[ReportSection.from_dict(_object(item)) for item in sections],
        )

    def save(self, report: Report) -> None:
        """Write the whole report. A temp file then a rename, so a reader never
        sees half a file."""

        payload = {
            "scene_id": report.scene_id,
            "question": report.question,
            "partner_id": report.partner_id,
            "phase": report.phase,
            "tool_order": list(report.tool_order),
            "synthesis_md": report.synthesis_md,
            "synthesis_source": report.synthesis_source,
            "sections": [asdict(section) for section in report.sections],
        }
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temp, path)


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("A report section is not a JSON object")
    return value


def _optional_str(raw: dict[str, object], key: str) -> str | None:
    """None when the key is absent or JSON null. Any other type is an error."""

    if key not in raw or raw[key] is None:
        return None
    value = raw[key]
    if isinstance(value, str):
        return value
    raise ValueError(f"{key} must be a string or null")


def _str_list(raw: dict[str, object], key: str) -> list[str]:
    """An empty list when the key is absent. A non-list is an error."""

    if key not in raw:
        return []
    value = raw[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    return list(value)


def _status(value: object) -> SectionStatus:
    if value == "done":
        return "done"
    if value == "waiting":
        return "waiting"
    if value == "locked":
        return "locked"
    if value == "running":
        return "running"
    if value == "failed":
        return "failed"
    raise ValueError(f"Unknown section status: {value!r}")


def _phase(value: object) -> Phase:
    if value == "planning":
        return "planning"
    if value == "running":
        return "running"
    if value == "writing":
        return "writing"
    if value == "done":
        return "done"
    raise ValueError(f"Unknown report phase: {value!r}")


def _source(value: object) -> BriefingSource:
    if value == "model":
        return "model"
    if value == "belt":
        return "belt"
    raise ValueError(f"Unknown briefing source: {value!r}")
