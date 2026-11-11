"""The two model calls behind a report: choose the tools, then phrase one result.

Both are plain prompt-to-model chains. Neither call is made here: ``plan`` and
``phrase`` send a request only when the caller invokes them, and
``chains_or_none`` builds nothing when no key is set.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from scene.analyze import load_local_env
from scene.paths import LISBON_SCENE_ID, project_root
from scene.report.facts import ReportFacts

MODEL_NAME = "gpt-4o-mini"

# The tool fields the planner may read. Raster links, measurements and briefing
# HTML stay out: choosing a tool needs what it answers, not what it produced.
_PLANNER_TOOL_KEYS = (
    "id",
    "label",
    "description",
    "locked",
    "reason",
    "needs_partner",
    "partners",
)

PLANNER_SYSTEM = (
    "You plan a short report about one radar scene. "
    "You are given a question, the scene's facts, the tools that exist, "
    "and the catalogue scenes that could pair with it. "
    "Select only the tools that answer the question, using their ids exactly "
    "as written. Do not select a tool the question does not need. "
    "List a catalogue scene id under catalogue_only only when the question "
    "asks about other dates or scenes. "
    "Set partner_id to one of the partners listed for amplitude-change when "
    "you select it, and to null otherwise. "
    "Use only ids that appear in the facts."
)

PHRASER_SYSTEM = (
    "You write the prose of one section of a radar scene report. "
    "You are given a question, one tool's measurement as JSON "
    "(a summary of labelled values, and a limit), and the scene's fields. "
    "Write a few plain sentences that answer the question from that JSON only. "
    "Repeat the limit sentence unchanged, word for word. "
    "State every summary number with its unit exactly as given. "
    "Name the mode, the incidence angle, the orbit, the look side, "
    "and the overview scale in metres per overview pixel. "
    "If the overview scale is null, say it is not available. "
    "Do not mention a ship, a spill, a tide height, or a cause "
    "unless it is in the JSON. "
    "Do not return JSON or a code block."
)


class PlanChoice(BaseModel):
    """The structured answer the planner must give. Ids are not checked here."""

    tools: list[str]
    catalogue_only: list[str]
    partner_id: str | None


class ReportChains:
    """The planner and the phraser, both built on one chat model."""

    def __init__(self, model: BaseChatModel) -> None:
        self._planner: Runnable[dict[str, str], dict[str, Any] | BaseModel] = (
            ChatPromptTemplate.from_messages(
                [("system", PLANNER_SYSTEM), ("human", "{request}")]
            )
            | model.with_structured_output(PlanChoice)
        )
        self._phraser: Runnable[dict[str, str], str] = (
            ChatPromptTemplate.from_messages(
                [("system", PHRASER_SYSTEM), ("human", "{request}")]
            )
            | model
            | StrOutputParser()
        )

    def plan(self, question: str, facts: ReportFacts) -> dict[str, object]:
        """The model's raw choice: ``tools``, ``catalogue_only``, ``partner_id``.

        No id is dropped here. ``validate_plan`` checks them against the facts.
        """

        reply = self._planner.invoke({"request": _planner_request(question, facts)})
        raw = reply.model_dump() if isinstance(reply, BaseModel) else reply
        return {
            "tools": raw.get("tools"),
            "catalogue_only": raw.get("catalogue_only"),
            "partner_id": raw.get("partner_id"),
        }

    def phrase(
        self, question: str, facts: ReportFacts, measurement: Mapping[str, object]
    ) -> str:
        """Prose for one tool's measurement, from its summary and limit only."""

        request = _phraser_request(question, facts, measurement)
        return self._phraser.invoke({"request": request})


def chains_or_none() -> ReportChains | None:
    """Build the chains when a key is set. Otherwise build no model at all.

    ``load_local_env`` reads .env first, and an environment value already set
    wins over it. A blank key counts as unset.
    """

    load_local_env()
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return None
    return ReportChains(ChatOpenAI(model=MODEL_NAME, temperature=0))


def _planner_request(question: str, facts: ReportFacts) -> str:
    """The question, the scene's facts, and the scene note when one exists."""

    payload = {
        "scene": _scene_fields(facts),
        "tools": [
            {key: tool[key] for key in _PLANNER_TOOL_KEYS if key in tool}
            for tool in facts.tools
        ],
        "catalogue_only": facts.catalogue_only,
    }
    parts = [f"Question: {question}", f"Facts:\n{_dump(payload)}"]
    if facts.scene_id == LISBON_SCENE_ID:
        note = (project_root() / "content" / "scene_note.md").read_text(
            encoding="utf-8"
        )
        parts.append(f"Scene note:\n{note}")
    return "\n\n".join(parts)


def _phraser_request(
    question: str, facts: ReportFacts, measurement: Mapping[str, object]
) -> str:
    """The question, one measurement's summary and limit, and the scene fields."""

    payload = {
        "summary": measurement.get("summary"),
        "limit": measurement.get("limit"),
        "scene": {
            "mode": facts.mode,
            "incidence_degrees": facts.incidence,
            "orbit": facts.orbit,
            "look": facts.look,
            "overview_metres": _overview(facts),
        },
    }
    return f"Question: {question}\n\nMeasurement:\n{_dump(payload)}"


def _scene_fields(facts: ReportFacts) -> dict[str, object]:
    """The scene fields a plan may rely on."""

    return {
        "scene_id": facts.scene_id,
        "mode": facts.mode,
        "incidence_degrees": facts.incidence,
        "orbit": facts.orbit,
        "look": facts.look,
        "band": facts.band,
        "polarization": facts.polarization,
        "collected_at": facts.collected_at,
    }


def _overview(facts: ReportFacts) -> dict[str, float] | None:
    """Metres per overview pixel as named columns and rows. None when unknown."""

    if facts.overview_metres is None:
        return None
    column, row = facts.overview_metres
    return {"column_metres": column, "row_metres": row}


def _dump(payload: object) -> str:
    """Stable, readable JSON for a prompt."""

    return json.dumps(payload, indent=2, ensure_ascii=False)
