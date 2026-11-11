"""Check the model's raw plan against the facts. Nothing unchecked passes."""

from __future__ import annotations

from scene.report.facts import ReportFacts
from scene.report.schema import LockedTool, ReportPlan

# The one tool that needs a second scene, so it waits instead of running.
WAITING_TOOL = "amplitude-change"


def validate_plan(facts: ReportFacts, raw: object) -> ReportPlan:
    """Keep only ids the facts allow.

    ``raw`` is the model's mapping: ``tools`` (tool ids), ``catalogue_only``
    (scene ids) and ``partner_id``. Anything malformed is treated as absent, so
    bad model output yields a smaller plan rather than an error.
    """

    named_tools = _names(raw, "tools")
    named_scenes = _names(raw, "catalogue_only")
    by_id = {str(tool["id"]): tool for tool in facts.tools}

    selected = [
        tool_id
        for tool_id in named_tools
        if tool_id != WAITING_TOOL and tool_id in by_id and not by_id[tool_id]["locked"]
    ]
    locked = [
        LockedTool(id=str(tool["id"]), reason=_reason(tool))
        for tool in facts.tools
        if tool["locked"]
    ]
    catalogue_only = [
        dict(row) for row in facts.catalogue_only if row["scene_id"] in named_scenes
    ]

    waiting_tool = by_id.get(WAITING_TOOL)
    waits = (
        WAITING_TOOL in named_tools
        and waiting_tool is not None
        and not waiting_tool["locked"]
    )
    partner_id = _partner(raw, waiting_tool) if waits else None
    return ReportPlan(
        selected=selected,
        waiting=[WAITING_TOOL] if waits else [],
        locked=locked,
        catalogue_only=catalogue_only,
        partner_id=partner_id,
    )


def _names(raw: object, key: str) -> list[str]:
    """Distinct strings under ``key``, in the order given. Else an empty list."""

    value = raw.get(key) if isinstance(raw, dict) else None
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, str) and item not in names:
            names.append(item)
    return names


def _reason(tool: dict[str, object]) -> str | None:
    """The belt's lock reason, when it gave one."""

    reason = tool.get("reason")
    return reason if isinstance(reason, str) else None


def _partner(raw: object, tool: dict[str, object] | None) -> str | None:
    """The suggested partner, only when it is one the tool lists as eligible."""

    candidate = raw.get("partner_id") if isinstance(raw, dict) else None
    partners = tool.get("partners") if tool is not None else None
    if isinstance(candidate, str) and isinstance(partners, list):
        return candidate if candidate in partners else None
    return None
