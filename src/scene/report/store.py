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


@dataclass(frozen=True)
class ReportSection:
    """What the report says about one tool."""

    tool_id: str
    status: SectionStatus
    # The belt's measurements.json (``summary`` and ``limit``). None until it ran.
    measurement: dict[str, object] | None
    briefing_md: str
    # ``model`` when the phraser's text kept the limit string, else ``belt``.
    briefing_source: BriefingSource
    overview_url: str | None
    # The second scene of an amplitude change. None for every other tool.
    partner_id: str | None

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> ReportSection:
        """Read one section back. A missing key raises, so a bad file fails fast."""

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
        )


@dataclass(frozen=True)
class Report:
    """The question asked and the sections written so far, in display order."""

    scene_id: str
    question: str
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

    def new(self, question: str, sections: list[ReportSection]) -> Report:
        """A report for this scene, before anything is saved."""

        return Report(self._scene_id, question, list(sections))

    def load(self) -> Report | None:
        """The saved report, or None when this scene has none."""

        if not self.path.is_file():
            return None
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return Report(
            scene_id=str(raw["scene_id"]),
            question=str(raw["question"]),
            sections=[ReportSection.from_dict(item) for item in raw["sections"]],
        )

    def save(self, report: Report) -> None:
        """Write the whole report. A temp file then a rename, so a reader never
        sees half a file."""

        payload = {
            "scene_id": report.scene_id,
            "question": report.question,
            "sections": [asdict(section) for section in report.sections],
        }
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temp, path)


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


def _source(value: object) -> BriefingSource:
    if value == "model":
        return "model"
    if value == "belt":
        return "belt"
    raise ValueError(f"Unknown briefing source: {value!r}")
