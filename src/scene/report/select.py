"""Choose the tools one report runs. The model does not choose the set."""

from __future__ import annotations

from dataclasses import dataclass

from scene.belt.catalog import ToolView, tool_spec, tools_for_scene

# The one pair tool. It runs only when the request names an eligible partner.
AMPLITUDE_TOOL = "amplitude-change"
_SINGLE_KINDS = frozenset({"single", "motion"})
_STACK_KINDS = frozenset({"stack", "stack-mean"})

# Stored on every report that includes a stack tool. A stack uses every match.
STACK_SCOPE = (
    "Stack tools compare every matched date, not only the chosen partner."
)


class IneligiblePartner(Exception):
    """``partner_id`` is not an unlocked amplitude-change partner on disk."""


@dataclass(frozen=True)
class IncludedTool:
    """One tool the report will measure, or list with the belt lock sentence."""

    id: str
    label: str
    description: str
    kind: str
    locked: bool
    reason: str


@dataclass(frozen=True)
class ToolSet:
    """The tools for one run, in belt catalog order.

    ``matched_dates`` counts the open scene plus every matched scene an
    unlocked stack tool will compare. It is None when no stack tool runs.
    """

    partner_id: str | None
    tools: tuple[IncludedTool, ...]
    matched_dates: int | None

    @property
    def runnable_ids(self) -> list[str]:
        """Unlocked tools, in catalog order. This is the order fallback."""

        return [tool.id for tool in self.tools if not tool.locked]


def choose_tools(scene_id: str, partner_id: str | None) -> ToolSet:
    """The set Start will run for this scene and this optional partner.

    With no partner, the set is every single-scene and motion tool, locked
    ones included as lock lines. Change and stack tools are left out entirely,
    including their lock lines. With a partner from the amplitude-change list,
    the set adds that comparison and every stack tool. A locked stack tool,
    including stack mean, is a section with the belt's lock sentence and is
    not run. ``matched_dates`` counts only a stack tool that will run. A
    partner the belt does not list, or a locked comparison, raises
    ``IneligiblePartner``. Catalogue scenes are never fetched.
    """

    views = tools_for_scene(scene_id)
    if partner_id is not None:
        _require_partner(views, partner_id)
    included: list[IncludedTool] = []
    matched_dates: int | None = None
    for view in views:
        kind = tool_spec(view.id).kind
        if kind in _SINGLE_KINDS:
            included.append(_include(view, kind))
            continue
        if partner_id is None:
            continue
        if view.id == AMPLITUDE_TOOL:
            included.append(_include(view, kind))
            continue
        if kind in _STACK_KINDS:
            included.append(_include(view, kind))
            # A locked stack tool is a section only. It does not compare dates.
            if matched_dates is None and not view.locked:
                matched_dates = len(view.partners) + 1
    return ToolSet(partner_id, tuple(included), matched_dates)


def nothing_runnable_sentence(chosen: ToolSet) -> str:
    """Why Start should not open a job. The belt's own reason when it gave one."""

    reason = next((tool.reason for tool in chosen.tools if tool.reason), "")
    lead = "No tool can run for this scene."
    if reason:
        return f"{lead} {reason}"
    return lead


def _require_partner(views: list[ToolView], partner_id: str) -> None:
    """Raise when amplitude change cannot compare ``partner_id``."""

    amplitude = next((view for view in views if view.id == AMPLITUDE_TOOL), None)
    if amplitude is None or amplitude.locked or partner_id not in amplitude.partners:
        raise IneligiblePartner(partner_id)


def _include(view: ToolView, kind: str) -> IncludedTool:
    return IncludedTool(
        id=view.id,
        label=view.label,
        description=view.description,
        kind=kind,
        locked=view.locked,
        reason=view.reason if view.locked else "",
    )
