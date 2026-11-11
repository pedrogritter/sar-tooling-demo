"""Render a saved report as a PDF.

This module reads only the stored report and the belt's ``overview.png`` files.
It never imports a chat model, so building a PDF needs no key and no network.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from scene.belt.catalog import analysis_dir, tool_spec
from scene.paths import valid_scene_id
from scene.report.store import Report, ReportSection

_FONT = "Helvetica"
_MARGIN_MM = 15
_LINE_MM = 5.5
_PICTURE_WIDTH_MM = 150
# A token this long cannot wrap inside a page, so it is split with a space.
_LONGEST_WORD = 70

_STATUS_TEXT = {
    "done": "Measured",
    "waiting": "Waiting for a second scene",
    "locked": "Locked for this scene",
    "running": "Still running",
    "failed": "Could not run",
}

# Typographic marks the built-in font cannot draw, and plain stand-ins.
_STAND_INS = {
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u2192": "->",
    "\u00a0": " ",
    "\u03c3": "sigma",
}
_MARKDOWN_MARKS = re.compile(r"(\*\*|__|`)")
_HEADING_MARKS = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)


def build_pdf(report: Report) -> bytes:
    """The whole report as PDF bytes: title, question, then every section.

    Locked and waiting sections are included, each with its own sentence.
    """

    pdf = FPDF(format="A4")
    pdf.set_margins(_MARGIN_MM, _MARGIN_MM, _MARGIN_MM)
    pdf.set_auto_page_break(True, margin=_MARGIN_MM)
    pdf.set_title(_plain(f"Scene report {report.scene_id}"))
    pdf.add_page()
    _heading(pdf, "Scene report", 18)
    _paragraph(pdf, f"Scene: {report.scene_id}")
    _paragraph(pdf, f"Question: {report.question}")
    if not report.sections:
        _paragraph(pdf, "This report has no sections yet.")
    for section in report.sections:
        _section(pdf, report.scene_id, section)
    return bytes(pdf.output())


def _section(pdf: FPDF, scene_id: str, section: ReportSection) -> None:
    pdf.ln(3)
    _heading(pdf, _label(section.tool_id), 14)
    _paragraph(pdf, _STATUS_TEXT[section.status], style="I")
    if section.partner_id:
        _paragraph(pdf, f"Compared with: {section.partner_id}")
    text = _plain(_HEADING_MARKS.sub("", section.briefing_md))
    for block in text.split("\n"):
        if block.strip():
            _paragraph(pdf, block)
    _measurement(pdf, section.measurement)
    picture = _picture(scene_id, section)
    if picture is not None:
        pdf.ln(2)
        pdf.image(str(picture), w=_PICTURE_WIDTH_MM)


def _measurement(pdf: FPDF, measurement: dict[str, object] | None) -> None:
    """The belt's labelled values, then its limit sentence."""

    if measurement is None:
        return
    summary = measurement.get("summary")
    if isinstance(summary, list):
        for row in summary:
            if isinstance(row, dict):
                _paragraph(pdf, f"- {row.get('label', '')}: {row.get('value', '')}")
    limit = measurement.get("limit")
    if isinstance(limit, str) and limit:
        _paragraph(pdf, f"Limit: {limit}")


def _picture(scene_id: str, section: ReportSection) -> Path | None:
    """The tool's overview.png when the file exists. Else None."""

    partner = section.partner_id
    if not valid_scene_id(scene_id) or (partner and not valid_scene_id(partner)):
        return None
    path = analysis_dir(scene_id, section.tool_id, partner) / "overview.png"
    return path if path.is_file() else None


def _label(tool_id: str) -> str:
    """The belt's tool label, or the id for a tool the belt no longer lists."""

    try:
        return _plain(tool_spec(tool_id).label)
    except KeyError:
        return _plain(tool_id)


def _heading(pdf: FPDF, text: str, size: int) -> None:
    pdf.set_font(_FONT, "B", size)
    pdf.multi_cell(0, _LINE_MM + 2, _plain(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _paragraph(pdf: FPDF, text: str, style: str = "") -> None:
    pdf.set_font(_FONT, style, 11)
    pdf.multi_cell(0, _LINE_MM, _plain(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _plain(text: str) -> str:
    """Text the built-in Latin-1 font can draw.

    Markdown marks are dropped, typographic marks get plain stand-ins, accents
    fold to their base letter when Latin-1 lacks them, and anything left over
    becomes ``?``. Very long tokens are split so they can wrap.
    """

    cleaned = _MARKDOWN_MARKS.sub("", text)
    for mark, stand_in in _STAND_INS.items():
        cleaned = cleaned.replace(mark, stand_in)
    kept: list[str] = []
    for char in cleaned:
        if ord(char) < 256:
            kept.append(char)
            continue
        base = unicodedata.normalize("NFKD", char).encode("latin-1", "ignore")
        kept.append(base.decode("latin-1") or "?")
    return " ".join(_split_long(token) for token in "".join(kept).split(" "))


def _split_long(token: str) -> str:
    if len(token) <= _LONGEST_WORD:
        return token
    return " ".join(
        token[start : start + _LONGEST_WORD]
        for start in range(0, len(token), _LONGEST_WORD)
    )
