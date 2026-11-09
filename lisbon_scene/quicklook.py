"""Turn the quicklook GeoTIFF into a PNG a browser can display.

The file is a cloud-optimized GeoTIFF. Its first image directory is the
full 4096 by 4096 raster; the later directories are overviews. Pixel
values stay in the product's own orientation. This module does not
georeference the raster and it does not look for objects in it.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError


class QuicklookError(Exception):
    """The quicklook file is present but cannot be encoded as a PNG."""


@dataclass(frozen=True)
class QuicklookImage:
    """PNG bytes plus the pixel size of the image the page shows."""

    png: bytes
    width: int
    height: int


def render_quicklook_png(path: Path, max_edge: int = 1600) -> QuicklookImage:
    """Read the full-resolution directory and downsample the long edge.

    ``max_edge`` keeps the page responsive. 1600 pixels is enough to see
    the bridge deck without shipping the full raster. BOX resampling is
    a plain downsample, not a filter meant to enhance targets.
    """

    if max_edge < 1:
        raise ValueError("max_edge must be at least 1")
    buffer = BytesIO()
    try:
        with Image.open(path) as image:
            # Directory 0 is the full raster. Later directories are overviews.
            image.seek(0)
            working = image.convert("L")
            width, height = working.size
            long_edge = max(width, height)
            if long_edge > max_edge:
                scale = max_edge / long_edge
                working = working.resize(
                    (max(1, round(width * scale)), max(1, round(height * scale))),
                    Image.Resampling.BOX,
                )
            working.save(buffer, format="PNG")
            rendered_width, rendered_height = working.size
    except (UnidentifiedImageError, OSError) as exc:
        raise QuicklookError(f"Could not read quicklook {path}: {exc}") from exc

    png = buffer.getvalue()
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise QuicklookError(f"Encoder did not produce a PNG for {path}")
    return QuicklookImage(png=png, width=rendered_width, height=rendered_height)
