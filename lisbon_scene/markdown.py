"""Render the scene note. The note is the only written report in v1.

The subset is headings, paragraphs, lists, bold, and inline code.
Everything else is escaped. A later answer step may quote this text;
it must not be able to smuggle HTML through the note.
"""

from __future__ import annotations

import html
import re

_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def render_markdown(source: str) -> str:
    """Turn scene-note markdown into HTML. Unknown markup stays text."""

    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []

    def flush_paragraph() -> None:
        text = " ".join(part.strip() for part in paragraph if part.strip())
        paragraph.clear()
        if text:
            blocks.append(f"<p>{_inline(text)}</p>")

    def flush_items() -> None:
        if not items:
            return
        body = "".join(f"<li>{_inline(item)}</li>" for item in items)
        items.clear()
        blocks.append(f"<ul>{body}</ul>")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_items()
            continue
        heading = _heading(stripped)
        if heading is not None:
            flush_paragraph()
            flush_items()
            level, text = heading
            blocks.append(f"<h{level}>{_inline(text)}</h{level}>")
            continue
        if stripped.startswith("- "):
            flush_paragraph()
            items.append(stripped[2:].strip())
            continue
        flush_items()
        paragraph.append(stripped)

    flush_paragraph()
    flush_items()
    return "\n".join(blocks)


def _heading(stripped: str) -> tuple[int, str] | None:
    marks, separator, text = stripped.partition(" ")
    if separator != " " or not text.strip():
        return None
    if not marks or any(char != "#" for char in marks) or len(marks) > 3:
        return None
    return len(marks), text.strip()


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=True)
    escaped = _CODE.sub(r"<code>\1</code>", escaped)
    return _BOLD.sub(r"<strong>\1</strong>", escaped)
