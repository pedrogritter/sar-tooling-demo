"""Order the tools, narrate one step, then write the lead.

Each is a plain prompt-to-model chain. Nothing is sent until the caller invokes
it, and ``chains_or_none`` builds nothing when no key is set. No call receives
a raster, a quicklook, or an overview image.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from scene.analyze import load_local_env
from scene.report.facts import ReportFacts
from scene.report.store import ReportSection

MODEL_NAME = "gpt-4o-mini"

# Scene fields a prompt may name. Paths, rasters, and catalogue rows stay out.
_SCENE_KEYS = (
    "scene_id",
    "mode",
    "incidence_degrees",
    "orbit",
    "look",
    "band",
    "polarization",
    "collected_at",
)

ORDER_SYSTEM = (
    "You order the tools of one radar scene report. "
    "You are given the scene and the tools that will run, with their ids. "
    "Return those ids in the order a reader should meet them. "
    "Use each id once. Add none, drop none, and invent none."
)

NARRATOR_SYSTEM = (
    "You write one or two sentences shown while one radar tool runs. "
    "Name the scene mode. "
    "Talk about the work this tool is doing, such as dark water, bright clusters, "
    "or a second date. "
    "Do not invent a ship, a spill, a tide, or a building. "
    "Do not state a measurement, a count, or a height. "
    "Do not return JSON or a code block."
)

SYNTHESIS_SYSTEM = (
    "You write the lead of one radar scene report. "
    "You are given the scene, every tool summary, "
    "every limit, the failures, the lock reasons, and a glossary. "
    "For a tool whose status is done, state its summary numbers with their "
    "units and its limit sentence. "
    "Give a hedged reading of what those numbers support, and name a limit "
    "that applies or a tool that failed. "
    "When you use a jargon word, pair it with a plain hint in the same sentence. "
    "The glossary is the only extra wording you may use. "
    "Do not name a ship, a spill, a tide height, or a building height. "
    "A bright return stays a bright radar return. "
    "Do not return JSON or a code block."
)


class OrderChoice(BaseModel):
    """The structured answer the order chain must give. Ids are checked by the run."""

    tools: list[str]


class ReportChains:
    """Order and synthesis at temperature 0, and the narrator at temperature 0.7."""

    def __init__(self, steady: BaseChatModel, narrator: BaseChatModel) -> None:
        self._order: Runnable[dict[str, str], dict[str, Any] | BaseModel] = (
            ChatPromptTemplate.from_messages(
                [("system", ORDER_SYSTEM), ("human", "{request}")]
            )
            | steady.with_structured_output(OrderChoice)
        )
        self._narrator: Runnable[dict[str, str], str] = (
            ChatPromptTemplate.from_messages(
                [("system", NARRATOR_SYSTEM), ("human", "{request}")]
            )
            | narrator
            | StrOutputParser()
        )
        self._synthesis: Runnable[dict[str, str], str] = (
            ChatPromptTemplate.from_messages(
                [("system", SYNTHESIS_SYSTEM), ("human", "{request}")]
            )
            | steady
            | StrOutputParser()
        )

    def order(
        self, facts: ReportFacts, tools: Sequence[Mapping[str, str]]
    ) -> list[str]:
        """The model's tool ids. The run keeps them only when they are a permutation."""

        reply = self._order.invoke({"request": _order_request(facts, tools)})
        raw = reply.model_dump() if isinstance(reply, BaseModel) else reply
        chosen = raw.get("tools") if isinstance(raw, dict) else None
        if not isinstance(chosen, list) or not all(
            isinstance(item, str) for item in chosen
        ):
            raise ValueError("The order is not a list of tool ids.")
        return list(chosen)

    def narrate(self, facts: ReportFacts, tool: Mapping[str, str]) -> str:
        """One or two sentences about the work about to run. No measurement yet."""

        return self._narrator.invoke({"request": _narrator_request(facts, tool)})

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
        """The lead, from summaries, limits, failures, locks, and the glossary."""

        request = _synthesis_request(
            facts, partner_id, sections, glossary, stack_scope, matched_dates
        )
        return self._synthesis.invoke({"request": request})


# A key typed on the page. It lives in this process and is never written out.
_session_key: str | None = None


def model_key_source() -> str:
    """Where the current key came from: ``unset``, ``session``, or ``environment``.

    The key itself is not returned. A blank value counts as unset. A key typed
    on the page matches ``session`` only while that same value is still the one
    in the environment.
    """

    load_local_env()
    current = os.environ.get("OPENAI_API_KEY", "").strip()
    if not current:
        return "unset"
    if _session_key is not None and current == _session_key:
        return "session"
    return "environment"


def remember_model_key(key: str) -> None:
    """Keep ``key`` for this process. Nothing is written to disk or the image."""

    global _session_key
    cleaned = key.strip()
    if not cleaned or any(char.isspace() for char in cleaned):
        raise ValueError("api_key must be a non-empty string without spaces")
    os.environ["OPENAI_API_KEY"] = cleaned
    _session_key = cleaned


def chains_or_none() -> ReportChains | None:
    """Build the chains when a key is set. Otherwise build no model at all.

    ``load_local_env`` reads .env first, and an environment value already set
    wins over it. A blank key counts as unset. A key kept by
    ``remember_model_key`` is already in the environment, so it is used too.
    Order and synthesis use temperature 0. The narrator uses temperature 0.7.
    """

    load_local_env()
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return None
    steady = ChatOpenAI(model=MODEL_NAME, temperature=0)
    narrator = ChatOpenAI(model=MODEL_NAME, temperature=0.7)
    return ReportChains(steady, narrator)


def _order_request(facts: ReportFacts, tools: Sequence[Mapping[str, str]]) -> str:
    """Scene fields and the runnable tools: id, label, and description only."""

    payload = {
        "scene": _scene_fields(facts),
        "tools": [_tool_fields(tool) for tool in tools],
    }
    return f"Order these tools.\n\n{_dump(payload)}"


def _narrator_request(facts: ReportFacts, tool: Mapping[str, str]) -> str:
    """The mode and one tool's description. No measurement and no picture."""

    payload = {
        "scene": {
            "mode": facts.mode,
            "incidence_degrees": facts.incidence,
            "orbit": facts.orbit,
            "look": facts.look,
        },
        "tool": _tool_fields(tool),
    }
    return f"Write the line for this tool.\n\n{_dump(payload)}"


def _synthesis_request(
    facts: ReportFacts,
    partner_id: str | None,
    sections: Sequence[ReportSection],
    glossary: str,
    stack_scope: str | None,
    matched_dates: int | None,
) -> str:
    """Facts, results, and the glossary. Picture paths are not included.

    A run with no partner and no matched-date count is told not to invent a
    second date, a stack, a partner, or a cause. Those fields are omitted
    from the payload so the invitation is not in the prompt.
    """

    payload: dict[str, object] = {
        "scene": {**_scene_fields(facts), "overview_metres": _overview(facts)},
        "results": [_result_row(section) for section in sections],
    }
    grounded = partner_id is not None or matched_dates is not None
    if grounded:
        payload["partner_id"] = partner_id
        payload["matched_dates"] = matched_dates
        payload["stack_scope"] = stack_scope
    parts = [f"Results:\n{_dump(payload)}", f"Glossary:\n{glossary}"]
    if stack_scope:
        parts.append(
            "Include this sentence, unchanged, because the stack tools compare "
            f"every matched date: {stack_scope}"
        )
    elif not grounded:
        parts.append(
            "Do not mention a second date, a stack, a partner, or a cause."
        )
    return "\n\n".join(parts)


def _result_row(section: ReportSection) -> dict[str, object]:
    """Summary, limit, and a failure or lock reason. No picture and no joke."""

    measurement = section.measurement or {}
    summary = measurement.get("summary")
    limit = measurement.get("limit")
    row: dict[str, object] = {
        "tool_id": section.tool_id,
        "status": section.status,
        "summary": summary if isinstance(summary, list) else [],
        "limit": limit if isinstance(limit, str) else "",
    }
    if section.status == "failed":
        row["failure"] = section.briefing_md
    if section.status == "locked":
        row["lock_reason"] = section.briefing_md
    return row


def _tool_fields(tool: Mapping[str, str]) -> dict[str, str]:
    """The three tool fields a prompt may read."""

    return {
        "id": str(tool.get("id", "")),
        "label": str(tool.get("label", "")),
        "description": str(tool.get("description", "")),
    }


def _scene_fields(facts: ReportFacts) -> dict[str, object]:
    """The scene fields a report may rely on. No file path is included."""

    fields = {
        "scene_id": facts.scene_id,
        "mode": facts.mode,
        "incidence_degrees": facts.incidence,
        "orbit": facts.orbit,
        "look": facts.look,
        "band": facts.band,
        "polarization": facts.polarization,
        "collected_at": facts.collected_at,
    }
    return {key: fields[key] for key in _SCENE_KEYS}


def _overview(facts: ReportFacts) -> dict[str, float] | None:
    """Metres per overview pixel as named columns and rows. None when unknown."""

    if facts.overview_metres is None:
        return None
    column, row = facts.overview_metres
    return {"column_metres": column, "row_metres": row}


def _dump(payload: object) -> str:
    """Stable, readable JSON for a prompt."""

    return json.dumps(payload, indent=2, ensure_ascii=False)
