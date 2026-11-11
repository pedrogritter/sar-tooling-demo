"""The checked plan a report is built from."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LockedTool:
    """A tool the belt keeps locked for this scene, with the belt's own reason."""

    id: str
    reason: str | None


@dataclass(frozen=True)
class ReportPlan:
    """What the model asked for, after every id was checked against the facts."""

    # Unlocked tools to run now. Never contains amplitude-change.
    selected: list[str] = field(default_factory=list)
    # ["amplitude-change"] when it is unlocked and named. It is not run.
    waiting: list[str] = field(default_factory=list)
    # Every locked tool, whether or not the model named it.
    locked: list[LockedTool] = field(default_factory=list)
    # Facts rows for the catalogue scenes the model named.
    catalogue_only: list[dict[str, str]] = field(default_factory=list)
    # A suggested partner for amplitude change. A suggestion, not a run.
    partner_id: str | None = None
