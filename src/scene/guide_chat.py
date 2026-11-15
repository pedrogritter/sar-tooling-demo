"""Answer one question about this viewer or about SAR.

An unrelated question does not call a model. A call receives the usage
guide, the glossary, and the scene note as text. It does not receive a
raster, a quicklook, or an overview image.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from scene.guide import guide_payload
from scene.paths import project_root

GuideModel = Callable[[str], str]
_MAX_CHARS = 500
EMPTY = "Enter a question."
TOO_LONG = "Ask in one short question."
BAD_PENDING = "pending_section_id must be null or a section id."
REFUSAL = (
    "This chat answers questions about this viewer and about SAR. "
    "It does not answer that."
)
NO_KEY = "Set an OpenAI key in Settings to ask a question."
BRIGHT = "A bright mark is a bright radar return."
YES_WORDS = frozenset({"yes", "y", "yeah", "ok", "okay"})
IN_SCOPE = (
    "sar",
    "radar",
    "sigma",
    "incidence",
    "look side",
    "speckle",
    "layover",
    "iceye",
    "catalogue",
    "catalog",
    "download",
    "library",
    "report",
    "quicklook",
    "bright return",
    "calibration",
    "polarization",
    "polarisation",
    "spotlight",
    "stripmap",
    "footprint",
    "stac",
    "glossary",
    "decibel",
    "dwell",
    "grd",
    "scene",
    "measurement",
)
ALLOWED = (
    "The page does not name a ship, match AIS, or claim that a model "
    "read the radar.",
    "The prose may not name a ship, a spill, a tide height, or a "
    "building height.",
    "A bright return on the water is not a vessel identification.",
)
CHAT_SYSTEM = (
    "You answer one question about this ICEYE open-data viewer or about "
    "SAR. Use the usage guide, the glossary, and the scene note below. "
    "You may also use what you know about SAR. Do not answer a subject "
    "outside this project. Do not name a ship, a spill, a tide height, "
    "or a building height. Do not match AIS. A bright return stays a "
    "bright radar return. Do not say that a model inspected a raster. "
    "If a tool limit sentence is in the material, keep that sentence "
    "unchanged. Do not run a tool and do not download a scene. Do not "
    "return JSON or a code block."
)


class GuideChatError(ValueError):
    """The question cannot be answered. The text is safe to show."""


def model_or_none() -> GuideModel | None:
    """A temperature-0 chat when a key is set. Otherwise nothing."""

    from scene.analyze import load_local_env
    from scene.report.chains import MODEL_NAME

    load_local_env()
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return None
    from langchain_openai import ChatOpenAI

    chat = ChatOpenAI(model=MODEL_NAME, temperature=0)

    def ask(prompt: str) -> str:
        reply = chat.invoke(prompt)
        content = getattr(reply, "content", "")
        return content if isinstance(content, str) else ""

    return ask


def answer_guide_chat(
    message: object,
    pending_section_id: object = None,
    model: GuideModel | None = None,
) -> dict[str, object]:
    """One turn. Unrelated questions and yes-opens do not call ``model``."""

    text = _message(message)
    pending = _pending(pending_section_id)
    sections = _sections()
    opened = _yes_open(text, pending, sections)
    if opened is not None:
        return opened
    matched = _match(text, sections)
    if matched is None and not _in_scope(text):
        return _payload(REFUSAL, None, False)
    if model is None:
        reply = NO_KEY
    else:
        reply = _from_model(text, matched, model)
    if matched is not None:
        reply = _with_offer(reply, str(matched["title"]))
        return _payload(reply, matched, False)
    return _payload(reply, None, False)


def _message(message: object) -> str:
    if not isinstance(message, str):
        raise GuideChatError(EMPTY)
    text = " ".join(message.split())
    if text == "":
        raise GuideChatError(EMPTY)
    if len(text) > _MAX_CHARS:
        raise GuideChatError(TOO_LONG)
    return text


def _pending(pending: object) -> str | None:
    if pending is None:
        return None
    if not isinstance(pending, str):
        raise GuideChatError(BAD_PENDING)
    cleaned = pending.strip()
    return cleaned or None


def _sections() -> list[dict[str, object]]:
    raw = guide_payload()["sections"]
    if not isinstance(raw, list):
        return []
    sections: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        section_id = item.get("id")
        title = item.get("title")
        paragraphs = item.get("paragraphs")
        if not isinstance(section_id, str) or not isinstance(title, str):
            continue
        if not isinstance(paragraphs, list):
            continue
        texts = [line for line in paragraphs if isinstance(line, str)]
        sections.append(
            {"id": section_id, "title": title, "paragraphs": texts}
        )
    return sections


def _yes_open(
    text: str,
    pending: str | None,
    sections: list[dict[str, object]],
) -> dict[str, object] | None:
    if pending is None or _fold(text).rstrip(".!") not in YES_WORDS:
        return None
    for section in sections:
        if section["id"] == pending:
            title = str(section["title"])
            return _payload(f"Opening {title}.", section, True)
    return None


def _match(
    text: str, sections: list[dict[str, object]]
) -> dict[str, object] | None:
    folded = _fold(text)
    for section in sections:
        title = _fold(str(section["title"]))
        if len(title) >= 4 and title in folded:
            return section
        section_id = str(section["id"])
        if section_id.startswith("tool-"):
            alias = section_id.removeprefix("tool-").replace("-", " ")
            if alias in folded:
                return section
    return None


def _in_scope(text: str) -> bool:
    folded = _fold(text)
    return any(phrase in folded for phrase in IN_SCOPE)


def _from_model(
    text: str, matched: dict[str, object] | None, model: GuideModel
) -> str:
    try:
        reply = model(_prompt(text)).strip()
    except Exception:
        reply = ""
    if matched is not None:
        limit = _limit(matched)
        if reply and not _forbidden(reply) and (limit is None or limit in reply):
            return reply
        return _section_fallback(matched)
    if reply and not _forbidden(reply):
        return reply
    return BRIGHT


def _prompt(text: str) -> str:
    root = project_root()
    glossary = (root / "content" / "sar_glossary.md").read_text(encoding="utf-8")
    note = (root / "content" / "scene_note.md").read_text(encoding="utf-8")
    blocks: list[str] = []
    for section in _sections():
        paragraphs = section["paragraphs"]
        lines = "\n".join(paragraphs) if isinstance(paragraphs, list) else ""
        blocks.append(f"{section['title']}\n{lines}")
    guide = "\n\n".join(blocks)
    return (
        f"{CHAT_SYSTEM}\n\nUsage guide:\n{guide}\n\nGlossary:\n{glossary}\n\n"
        f"Scene note:\n{note}\n\nQuestion:\n{text}"
    )


def _limit(section: dict[str, object]) -> str | None:
    if not str(section["id"]).startswith("tool-"):
        return None
    paragraphs = section["paragraphs"]
    if not isinstance(paragraphs, list) or not paragraphs:
        return None
    last = paragraphs[-1]
    return last if isinstance(last, str) else None


def _section_fallback(section: dict[str, object]) -> str:
    paragraphs = section["paragraphs"]
    if isinstance(paragraphs, list):
        text = " ".join(line for line in paragraphs if isinstance(line, str))
        if text:
            return text
    return BRIGHT


def _with_offer(reply: str, title: str) -> str:
    offer = f"Open the {title} section?"
    if offer in reply:
        return reply
    return f"{reply.rstrip()} {offer}"


def _forbidden(reply: str) -> bool:
    lowered = reply.casefold()
    if "inspected a raster" in lowered or "inspected the radar" in lowered:
        return True
    stripped = reply
    for sentence in ALLOWED:
        stripped = stripped.replace(sentence, "")
    folded = stripped.casefold()
    return any(word in folded for word in ("ship", "vessel", "ais", "spill"))


def _payload(
    reply: str, section: dict[str, object] | None, open_section: bool
) -> dict[str, object]:
    if section is None:
        return {
            "reply": reply,
            "section_id": None,
            "section_title": None,
            "open_section": open_section,
        }
    return {
        "reply": reply,
        "section_id": section["id"],
        "section_title": section["title"],
        "open_section": open_section,
    }


def _fold(text: str) -> str:
    return " ".join(text.casefold().split())