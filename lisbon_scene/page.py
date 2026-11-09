"""Build the single HTML page for this scene.

The page shows the quicklook, the STAC fields, and the scene note.
It states that no detector has run. It has no question box: answering
is a later slice, and that slice may only use the text already here.
"""

from __future__ import annotations

import html
from datetime import datetime

from .loader import SceneRecord
from .markdown import render_markdown

_LIMIT = (
    "This page shows the quicklook and the STAC record for one collect. "
    "The note was written by a person. No detector has run. "
    "Nothing on this page is a vessel, vehicle, or aircraft detection, "
    "and nothing here is matched to AIS."
)


def render_page(
    scene: SceneRecord,
    note_markdown: str,
    quicklook_width: int | None = None,
    quicklook_height: int | None = None,
) -> str:
    """Return the full document. Every STAC value is escaped.

    Pass both quicklook dimensions when the PNG was encoded. Omit them
    when the file is not on disk and the page should say so.
    """

    image = _figure(scene, quicklook_width, quicklook_height)
    facts = "\n".join(
        (
            _fact("Collected", _format_utc(scene.collected_at)),
            _fact(
                "Window",
                f"{_format_utc(scene.start_at)} – {_format_utc(scene.end_at)}",
            ),
            _fact("Platform", scene.platform),
            _fact("Mode", scene.mode),
            _fact("Band", scene.band),
            _fact("Polarization", ", ".join(scene.polarizations)),
            _fact("Orbit", scene.orbit_state),
            _fact("Incidence angle", f"{scene.incidence_angle:.1f}°"),
            _fact("Bounding box", _format_bbox(scene)),
            _fact("On disk", _local_assets(scene)),
            _fact("Not downloaded", _remote_assets(scene)),
        )
    )
    note_html = render_markdown(note_markdown)
    scene_id = html.escape(scene.scene_id)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lisbon spotlight — 25 de Abril</title>
  <link rel="stylesheet" href="/static/scene.css">
</head>
<body>
  <main class="scene">
    <header class="scene__header">
      <p class="scene__kicker">ICEYE open data · one spotlight frame</p>
      <h1 class="scene__title">25 de Abril bridge</h1>
      <p class="scene__id">{scene_id}</p>
    </header>
    <p class="scene__limit" role="note">{html.escape(_LIMIT)}</p>
    <div class="scene__layout">
      {image}
      <section class="scene__meta" aria-labelledby="collect-heading">
        <h2 class="scene__heading" id="collect-heading">Collect</h2>
        <dl class="scene__facts">
          {facts}
        </dl>
      </section>
    </div>
    <article class="scene__note">
      {note_html}
    </article>
  </main>
  <script src="/static/scene.js"></script>
</body>
</html>
"""


def _figure(
    scene: SceneRecord,
    quicklook_width: int | None,
    quicklook_height: int | None,
) -> str:
    caption = (
        "Quicklook raster from qlk-cog.tif, downsampled for this page. "
        "Pixels stay in the product orientation. This is not a map overlay "
        "and not a detection layer."
    )
    escaped_caption = html.escape(caption)
    if quicklook_width is None or quicklook_height is None:
        return (
            '<figure class="scene__figure">'
            '<p class="scene__missing">The quicklook file is not on disk. '
            "From the repository root, run python3 scene.py.</p>"
            f'<figcaption class="scene__caption">{escaped_caption}</figcaption>'
            "</figure>"
        )
    alt = f"SAR quicklook of {scene.scene_id}, covering the 25 de Abril bridge"
    return (
        '<figure class="scene__figure">'
        f'<img class="scene__image" src="/quicklook.png" alt="{html.escape(alt)}" '
        f'width="{quicklook_width}" height="{quicklook_height}">'
        f'<figcaption class="scene__caption">{escaped_caption}</figcaption>'
        "</figure>"
    )


def _fact(label: str, value: str) -> str:
    return (
        '<div class="scene__fact">'
        f"<dt>{html.escape(label)}</dt>"
        f"<dd>{html.escape(value)}</dd>"
        "</div>"
    )


def _format_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.strftime("%d %B %Y, %H:%M:%S UTC")


def _format_bbox(scene: SceneRecord) -> str:
    box = scene.bbox
    return (
        f"{box.west:.3f}, {box.south:.3f}, {box.east:.3f}, {box.north:.3f}"
        " (west, south, east, north)"
    )


def _local_assets(scene: SceneRecord) -> str:
    names = [asset.local_path.name for asset in scene.assets if asset.local_path]
    return ", ".join(names) if names else "none"


def _remote_assets(scene: SceneRecord) -> str:
    titles = [asset.title for asset in scene.assets if not asset.on_disk]
    return ", ".join(titles) if titles else "none"
