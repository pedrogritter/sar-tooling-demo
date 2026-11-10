"""Draw a decibel backdrop, translucent classes, and a legend under the picture."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

Color = tuple[int, int, int]


@dataclass(frozen=True)
class MaskLayer:
    mask: np.ndarray
    color: Color
    alpha: float = 0.45


@dataclass(frozen=True)
class Stroke:
    points: tuple[tuple[float, float], ...]
    color: Color
    width: int = 2


def render(
    gray: np.ndarray,
    layers: list[MaskLayer],
    strokes: list[Stroke],
    legend: list[str],
) -> Image.Image:
    """Compose the stage image. ``gray`` is 0–1. The legend is part of the PNG."""

    height, width = gray.shape
    rgb = np.dstack([gray, gray, gray])
    for layer in layers:
        if layer.mask.shape != gray.shape or not layer.mask.any():
            continue
        color = np.array(layer.color, dtype=np.float32) / 255
        mask = layer.mask
        rgb[mask] = (1 - layer.alpha) * rgb[mask] + layer.alpha * color
    image = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), mode="RGB")
    draw = ImageDraw.Draw(image)
    for stroke in strokes:
        if len(stroke.points) == 1:
            col, row = stroke.points[0]
            radius = 4
            draw.ellipse(
                [col - radius, row - radius, col + radius, row + radius],
                outline=stroke.color,
                width=2,
            )
            continue
        if len(stroke.points) >= 2:
            draw.line(list(stroke.points), fill=stroke.color, width=stroke.width)
    return with_legend(image, legend)


def with_legend(image: Image.Image, legend: list[str]) -> Image.Image:
    """Append the legend under an image that is already RGB."""

    if not legend:
        return image
    line_h = 14
    pad = 6
    panel_h = pad * 2 + line_h * len(legend)
    canvas = Image.new("RGB", (image.width, image.height + panel_h), (12, 12, 12))
    canvas.paste(image, (0, 0))
    pen = ImageDraw.Draw(canvas)
    for index, line in enumerate(legend):
        pen.text(
            (pad, image.height + pad + index * line_h), line[:140], fill=(230, 230, 230)
        )
    return canvas


def attach_bars(
    image: Image.Image,
    labels: list[str],
    values: list[float | None],
) -> Image.Image:
    """Place a sea-state bar chart to the right of the picture."""

    width = 240
    chart = Image.new("RGB", (width, image.height), (12, 12, 12))
    pen = ImageDraw.Draw(chart)
    finite = [value for value in values if value is not None]
    if not finite:
        pen.text((8, 8), "No water median", fill=(230, 230, 230))
    else:
        low = min(finite) - 1
        high = max(finite) + 1
        span = max(high - low, 1)
        top = 16
        row_h = max(12, (image.height - top - 8) // max(len(values), 1))
        for index, (label, value) in enumerate(zip(labels, values, strict=True)):
            y = top + index * row_h
            pen.text((4, y), label[:12], fill=(180, 180, 180))
            if value is None:
                continue
            length = int((value - low) / span * (width - 90))
            pen.rectangle(
                [78, y + 2, 78 + max(length, 1), y + 10], fill=(120, 180, 210)
            )
    canvas = Image.new("RGB", (image.width + width, image.height), (12, 12, 12))
    canvas.paste(image, (0, 0))
    canvas.paste(chart, (image.width, 0))
    return canvas
