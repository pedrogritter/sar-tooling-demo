"""Render a saved report as a PDF.

This module reads only the stored report and the belt's ``overview.png`` files.
It never imports a chat model, so building a PDF needs no key and no network.
``write_pdf`` is the only function that loads WeasyPrint, and the route calls
the model nowhere on this path. The narrator line is not part of the document.
"""

from __future__ import annotations

import html
import importlib
from pathlib import Path

from scene.belt.catalog import analysis_dir, tool_spec
from scene.paths import valid_scene_id
from scene.report.store import Report, ReportSection

_STATUS_TEXT = {
    "done": "Measured",
    "waiting": "Waiting for a second scene",
    "locked": "Locked for this scene",
    "running": "Still running",
    "failed": "Could not run",
}


def build_pdf(report: Report) -> bytes:
    """The whole report as PDF bytes. The model is not called."""

    return write_pdf(render_html(report))


def render_html(report: Report) -> str:
    """One HTML document: lead, then each tool on its own page.

    CSS lives in the document. Page headers and page numbers are ``@page``
    rules, which a style attribute cannot carry. Local ``overview.png`` paths
    are file URIs so WeasyPrint can read them without a network fetch.
    """

    scene_id = html.escape(report.scene_id)
    header_id = report.scene_id if valid_scene_id(report.scene_id) else ""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>Scene report {scene_id}</title>",
        "<style>",
        _css(header_id),
        "</style>",
        "</head>",
        "<body>",
        "<h1>Scene report</h1>",
        f"<p>Scene: {scene_id}</p>",
    ]
    if report.question.strip():
        parts.append(f"<p>Question: {html.escape(report.question)}</p>")
    if report.partner_id:
        parts.append(f"<p>Partner scene: {html.escape(report.partner_id)}</p>")
    parts.append('<section class="synthesis">')
    parts.append("<h2>Reading</h2>")
    parts.append(_blocks(report.synthesis_md or "This report has no reading yet."))
    parts.append("</section>")
    if not report.sections:
        parts.append("<p>This report has no sections yet.</p>")
    for section in _document_sections(report):
        parts.append(_section(report.scene_id, section))
    parts.append("</body></html>")
    return "\n".join(parts)


def write_pdf(html_document: str) -> bytes:
    """Turn one HTML document into PDF bytes.

    WeasyPrint is imported here so importing this module, and tests that mock
    this function, do not need the Pango libraries.
    """

    module = importlib.import_module("weasyprint")
    document = getattr(module, "HTML")(string=html_document)
    payload = document.write_pdf()
    if not isinstance(payload, bytes | bytearray):
        raise RuntimeError("The report PDF could not be written.")
    return bytes(payload)


def _section(scene_id: str, section: ReportSection) -> str:
    """One tool. The progress note is the live joke, so it is left out."""

    label = html.escape(_label(section.tool_id))
    parts = [
        '<section class="tool">',
        f"<h2>{label}</h2>",
        f'<p class="status">{html.escape(_STATUS_TEXT[section.status])}</p>',
    ]
    if section.partner_id:
        parts.append(f"<p>Compared with: {html.escape(section.partner_id)}</p>")
    if section.status == "done":
        parts.append(_summary(section.measurement))
    elif section.briefing_md.strip():
        parts.append(_blocks(section.briefing_md))
    picture = _picture(scene_id, section)
    if picture is not None and section.status == "done":
        src = html.escape(picture.resolve().as_uri(), quote=True)
        parts.append(f'<img src="{src}" alt="{label}">')
    parts.append("</section>")
    return "\n".join(parts)


def _summary(measurement: dict[str, object] | None) -> str:
    """The belt's labelled values, then its limit sentence."""

    if measurement is None:
        return ""
    parts: list[str] = []
    summary = measurement.get("summary")
    if isinstance(summary, list):
        items: list[str] = []
        for row in summary:
            if isinstance(row, dict):
                item_label = html.escape(str(row.get("label", "")))
                value = html.escape(str(row.get("value", "")))
                items.append(f"<li>{item_label}: {value}</li>")
        if items:
            parts.append("<ul>" + "".join(items) + "</ul>")
    limit = measurement.get("limit")
    if isinstance(limit, str) and limit:
        parts.append(f'<p class="limit">Limit: {html.escape(limit)}</p>')
    return "\n".join(parts)


def _document_sections(report: Report) -> list[ReportSection]:
    """Done tools in run order, then locked, waiting, failed, and still running.

    An older file has no ``tool_order``. Its sections stay in the saved order
    inside each status.
    """

    buckets: dict[str, list[ReportSection]] = {
        "done": [],
        "locked": [],
        "waiting": [],
        "failed": [],
        "running": [],
    }
    if report.tool_order:
        by_id = {section.tool_id: section for section in report.sections}
        seen: set[str] = set()
        ordered = [_take(by_id, tool_id, seen) for tool_id in report.tool_order]
        for section in [item for item in ordered if item is not None]:
            buckets.setdefault(section.status, []).append(section)
        leftovers = [
            section for section in report.sections if section.tool_id not in seen
        ]
    else:
        leftovers = list(report.sections)
    for section in leftovers:
        buckets.setdefault(section.status, []).append(section)
    return [
        *buckets["done"],
        *buckets["locked"],
        *buckets["waiting"],
        *buckets["failed"],
        *buckets["running"],
    ]


def _take(
    by_id: dict[str, ReportSection], tool_id: str, seen: set[str]
) -> ReportSection | None:
    section = by_id.get(tool_id)
    if section is None or tool_id in seen:
        return None
    seen.add(tool_id)
    return section


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
        return tool_spec(tool_id).label
    except KeyError:
        return tool_id


def _blocks(text: str) -> str:
    """Escape text and keep each non-empty line as its own paragraph."""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(f"<p>{html.escape(line)}</p>" for line in lines)


def _css(scene_id: str) -> str:
    """A4, a running header, page numbers, and a break before every tool."""

    header = html.escape(scene_id, quote=True)
    return f"""
@page {{
  size: A4;
  margin: 18mm 16mm 20mm 16mm;
  @top-left {{
    content: "Scene report";
    font-family: "Liberation Sans", sans-serif;
    font-size: 9pt;
    color: #444;
  }}
  @top-right {{
    content: "{header}";
    font-family: "Liberation Sans", sans-serif;
    font-size: 9pt;
    color: #444;
  }}
  @bottom-right {{
    content: counter(page) " / " counter(pages);
    font-family: "Liberation Sans", sans-serif;
    font-size: 9pt;
    color: #444;
  }}
}}
body {{
  font-family: "Liberation Sans", sans-serif;
  font-size: 11pt;
  line-height: 1.45;
  color: #1a1a1a;
}}
h1 {{
  font-size: 18pt;
  margin: 0 0 8pt;
}}
h2 {{
  font-size: 14pt;
  margin: 0 0 6pt;
}}
p {{
  margin: 0 0 6pt;
}}
.status {{
  font-style: italic;
}}
.tool {{
  break-before: page;
  page-break-before: always;
}}
img {{
  width: 150mm;
  height: auto;
  margin-top: 8pt;
}}
"""
