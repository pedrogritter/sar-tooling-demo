"""Lisbon scene for an empty data directory.

``demo/lisbon`` is the committed source. When that tree holds ``stac.json``
and ``preview.png``, and no radar raster, ``write_seed`` copies it into
``demo/seed`` and writes ``demo.json`` with ``seeded`` set. That marker is
not the drawn placeholder: the pictures and the analysis stay real
measurements, and the page can still clear them. When that tree is missing,
the pictures and numbers are drawn in this process. They are not an ICEYE
raster and they are not a measurement, and ``demo.json`` then has
``placeholder`` set. ``seed_if_needed`` copies the seed when the Lisbon
scene folder is missing or empty. A folder that already holds files is left
alone, even when ``stac.json`` is missing. A copied pack that is already on
disk and has no marker yet receives the seeded marker on the next start.
Clearing the demo leaves ``stac.json``, so the next start does not put the
pictures back. If that record is then removed and the folder is empty, the
following start seeds again. A real download removes the seeded files only
after it finishes.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Collection
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .paths import LISBON_SCENE_ID, data_dir, project_root

PLACEHOLDER_NOTE = (
    "Demo placeholder. These pictures and numbers were not measured "
    "from an ICEYE raster."
)
SEEDED_NOTE = (
    "Demo data copied from the Lisbon pack. "
    "The radar products are not in this folder."
)
SEED_MARKER = ".seed-applied"
DEMO_FILE = "demo.json"
# Files the seed may write. A download that replaces one of these keeps it.
_SEED_FILES = ("qlk-cog.tif", "graphic.png", "preview.png", "vid-mp4.mp4")

# Radar products. A committed seed that contains one of these is refused.
_RASTER_NAMES = frozenset(
    {
        "grd-cog.tif",
        "slc-cog.tif",
        "csi-cog.tif",
        "vid-cog.tif",
        "qlk-cog.tif",
    }
)

# Single-scene tools. Motion, change, and stack stay locked with no picture.
_TOOLS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "open-water",
        "Open water",
        (
            ("Water area", "0 km² placeholder"),
            ("Water fraction", "0 placeholder"),
            ("Median sigma-nought", "0 dB placeholder"),
        ),
    ),
    (
        "sea-roughness",
        "Sea roughness",
        (
            ("Calm area", "0 km² placeholder"),
            ("Rough area", "0 km² placeholder"),
            ("Calm median", "0 dB placeholder"),
            ("Rough median", "0 dB placeholder"),
        ),
    ),
    (
        "built-up",
        "Built-up return",
        (
            ("Built-up fraction of land", "0 placeholder"),
            ("Clusters", "0 placeholder"),
        ),
    ),
    (
        "returns-on-water",
        "Returns on water",
        (
            ("Bright returns", "0 placeholder"),
        ),
    ),
    (
        "long-structure",
        "Long structure",
        (
            ("Length", "0 m placeholder"),
            ("Width", "0 m placeholder"),
            ("Peak sigma-nought", "0 dB placeholder"),
        ),
    ),
)


class PlaceholderMissing(Exception):
    """Clear was asked for, and no scene folder is marked as a placeholder."""


class SeedRasterError(Exception):
    """The Lisbon seed source contains a radar raster, which must not be copied."""


def note_from_folder(folder: Path) -> str | None:
    """The placeholder sentence, or None when this folder is not a drawing."""

    payload = _demo_payload(folder)
    if payload is None or payload.get("placeholder") is not True:
        return None
    return _note(payload, PLACEHOLDER_NOTE)


def seed_note_from_folder(folder: Path) -> str | None:
    """The seeded-pack sentence, or None when this folder is not that pack.

    A drawn placeholder is not a seeded pack, even if both flags were set.
    """

    payload = _demo_payload(folder)
    if payload is None or payload.get("placeholder") is True:
        return None
    if payload.get("seeded") is not True:
        return None
    return _note(payload, SEEDED_NOTE)


def seed_if_needed(data: Path | None = None, seed: Path | None = None) -> bool:
    """Copy the placeholder scene when the Lisbon folder is missing or empty.

    Returns True only on the copy. An existing ``stac.json`` is left
    untouched, and so is a folder that already contains any file. The
    ``.seed-applied`` marker does not block a later copy once that folder
    is empty again.
    """

    root = data if data is not None else data_dir()
    folder = root / "scenes" / LISBON_SCENE_ID
    if (folder / "stac.json").is_file() or _occupied(folder):
        # An older copy of the pack has the pictures and no marker.
        _mark_existing_seed(folder)
        return False
    source = seed if seed is not None else seed_tree()
    origin = source / "scenes" / LISBON_SCENE_ID
    if not (origin / "stac.json").is_file():
        raise FileNotFoundError(f"Placeholder seed is missing: {origin}")
    folder.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(origin, folder, dirs_exist_ok=True)
    _write_marker(root, "seeded")
    return True


def seed_tree() -> Path:
    """Build ``demo/seed`` when the image does not already contain it."""

    dest = project_root() / "demo" / "seed"
    if not (dest / "scenes" / LISBON_SCENE_ID / "stac.json").is_file():
        write_seed(dest)
    return dest


def clear_placeholder(data: Path | None = None) -> str:
    """Remove seeded or placeholder pictures and keep the STAC record.

    Raises PlaceholderMissing when no scene folder carries a clearable
    ``demo.json``. Other scene folders are not deleted. ``stac.json`` stays,
    so the next start does not copy the pictures back.
    """

    root = data if data is not None else data_dir()
    scenes = root / "scenes"
    note = PLACEHOLDER_NOTE
    cleared = False
    if scenes.is_dir():
        for child in sorted(scenes.iterdir()):
            if not child.is_dir():
                continue
            found = note_from_folder(child) or seed_note_from_folder(child)
            if found is None:
                continue
            note = found
            _remove_placeholder_payload(child)
            cleared = True
    if not cleared:
        raise PlaceholderMissing("No demo placeholder is on disk")
    _write_marker(root, "cleared")
    return note


def strip_placeholder(
    folder: Path, replaced: Collection[str] | None = None
) -> bool:
    """Drop the placeholder after a real download has finished.

    ``replaced`` is the set of filenames that download wrote. A drawn
    quicklook or thumbnail in that set is the new file and stays. One that
    was not written is still the seed and is deleted. ``demo.json`` and
    ``analysis/`` always go. A folder without ``demo.json`` is left as it
    is, which is also why a failed download must not call this.
    """

    if note_from_folder(folder) is None and seed_note_from_folder(folder) is None:
        return False
    _remove_placeholder_payload(folder, kept=replaced)
    _write_marker(_data_root(folder), "replaced")
    return True


def preview_file(folder: Path) -> Path | None:
    """``preview.png`` beside the scene record, when the seed stores one.

    This is the rendered quicklook, not ``qlk-cog.tif``. The library uses it
    so a scene with no raster still has a quicklook URL.
    """

    path = folder / "preview.png"
    if path.is_file():
        return path
    return None


def write_seed(dest: Path, source: Path | None = None) -> Path:
    """Copy the committed Lisbon tree, or draw the placeholder when it is absent.

    ``source`` defaults to ``demo/lisbon``. The copy runs only when that tree
    contains ``stac.json`` and ``preview.png``. It does not draw the gray
    frame and it does not write ``demo.json``. A radar COG in the source
    raises ``SeedRasterError`` so the raster never enters ``demo/seed``.
    """

    origin = project_root() / "demo" / "lisbon" if source is None else source
    raster = _raster_name(origin)
    if raster is not None:
        raise SeedRasterError(
            f"Lisbon seed must not contain a radar raster ({raster})"
        )
    scene = _committed_scene(origin)
    if scene is None:
        return _write_placeholder(dest)
    return _copy_committed(dest, scene)


def _committed_scene(origin: Path) -> Path | None:
    """Scene folder when it holds both ``stac.json`` and ``preview.png``."""

    nested = origin / "scenes" / LISBON_SCENE_ID
    for folder in (nested, origin):
        if (folder / "stac.json").is_file() and preview_file(folder) is not None:
            return folder
    return None


def _raster_name(origin: Path) -> str | None:
    """First forbidden radar filename under ``origin``, if one is present."""

    if not origin.exists():
        return None
    if origin.is_file():
        return origin.name if origin.name in _RASTER_NAMES else None
    for path in origin.rglob("*"):
        if path.is_file() and path.name in _RASTER_NAMES:
            return path.name
    return None


def _copy_committed(dest: Path, scene: Path) -> Path:
    """Copy one scene folder. ``demo.json`` marks a drawing and stays out."""

    folder = dest / "scenes" / LISBON_SCENE_ID
    if folder.exists():
        shutil.rmtree(folder)
    folder.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(scene, folder, ignore=shutil.ignore_patterns(DEMO_FILE))
    _write_seed_marker(folder)
    return dest


def _write_placeholder(dest: Path) -> Path:
    """Write the small drawn tree. No radar product is read or stored."""

    folder = dest / "scenes" / LISBON_SCENE_ID
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    (folder / "stac.json").write_text(
        json.dumps(_stac_item(), indent=2) + "\n",
        encoding="utf-8",
    )
    (folder / DEMO_FILE).write_text(
        json.dumps({"placeholder": True, "note": PLACEHOLDER_NOTE}, indent=2) + "\n",
        encoding="utf-8",
    )
    _picture("Quicklook").save(folder / "qlk-cog.tif", format="TIFF")
    _picture("Thumbnail").save(folder / "graphic.png", format="PNG")
    for tool_id, title, rows in _TOOLS:
        analysis = folder / "analysis" / tool_id
        analysis.mkdir(parents=True)
        _picture(title).save(analysis / "overview.png", format="PNG")
        payload = {
            "tool_id": tool_id,
            "scene_id": LISBON_SCENE_ID,
            "partner_id": None,
            "summary": [{"label": label, "value": value} for label, value in rows],
            "limit": PLACEHOLDER_NOTE,
        }
        (analysis / "measurements.json").write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        lines = [f"# {title}", "", PLACEHOLDER_NOTE, ""]
        lines.extend(f"- {label}: {value}" for label, value in rows)
        lines.append("")
        (analysis / "briefing.md").write_text("\n".join(lines), encoding="utf-8")
    return dest


def _occupied(folder: Path) -> bool:
    """True when the scene folder exists and already holds a file or directory."""

    if not folder.exists():
        return False
    if not folder.is_dir():
        return True
    return any(folder.iterdir())


def _data_root(folder: Path) -> Path:
    """Data directory for a scene at ``data/scenes/<id>``."""

    scenes = folder.parent
    if scenes.name == "scenes":
        return scenes.parent
    return scenes.parent


def _remove_placeholder_payload(
    folder: Path, kept: Collection[str] | None = None
) -> None:
    """Delete the marker and the files the seed wrote.

    ``stac.json`` and any radar product stay, so a download is not removed.
    A name in ``kept`` was just written by that download and stays too.
    """

    skip = set(kept or ())
    for name in (DEMO_FILE, *_SEED_FILES):
        if name in skip:
            continue
        path = folder / name
        if path.is_file():
            path.unlink()
    for name in ("analysis", "report"):
        path = folder / name
        if path.is_dir():
            shutil.rmtree(path)


def _demo_payload(folder: Path) -> dict[str, object] | None:
    """``demo.json`` when it is an object. A missing or broken file is None."""

    path = folder / DEMO_FILE
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _note(payload: dict[str, object], fallback: str) -> str:
    note = payload.get("note")
    if isinstance(note, str) and note.strip():
        return note.strip()
    return fallback


def _write_seed_marker(folder: Path) -> None:
    """Mark a copied Lisbon pack. This is not the drawn placeholder."""

    folder.mkdir(parents=True, exist_ok=True)
    (folder / DEMO_FILE).write_text(
        json.dumps(
            {"placeholder": False, "seeded": True, "note": SEEDED_NOTE},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _mark_existing_seed(folder: Path) -> None:
    """Add the seeded marker to a pack that was copied before the marker existed.

    A radar product in the folder means a download already landed, so the
    pictures are left unmarked. A placeholder marker is also left as it is.
    """

    if not folder.is_dir() or _demo_payload(folder) is not None:
        return
    if preview_file(folder) is None or _raster_name(folder) is not None:
        return
    _write_seed_marker(folder)


def _write_marker(root: Path, reason: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / SEED_MARKER).write_text(reason + "\n", encoding="utf-8")


def _stac_item() -> dict[str, object]:
    """Public facts for the 25 de Abril collect. Assets are names only."""

    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": LISBON_SCENE_ID,
        "bbox": [
            -9.213969443201776,
            38.65979028852499,
            -9.139894173828166,
            38.71784777157828,
        ],
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-9.213969443201776, 38.65979028852499],
                    [-9.139894173828166, 38.65979028852499],
                    [-9.139894173828166, 38.71784777157828],
                    [-9.213969443201776, 38.71784777157828],
                    [-9.213969443201776, 38.65979028852499],
                ]
            ],
        },
        "properties": {
            "datetime": "2025-10-24T13:53:16.995Z",
            "start_datetime": "2025-10-24T13:53:09.803Z",
            "end_datetime": "2025-10-24T13:53:24.188Z",
            "platform": "ICEYE-X52",
            "sar:instrument_mode": "spotlight",
            "sar:frequency_band": "X",
            "sar:polarizations": ["VV"],
            "sat:orbit_state": "descending",
            "view:incidence_angle": 32.035387,
        },
        "assets": {
            "graphic": {
                "href": "https://example.invalid/graphic.png",
                "type": "image/png",
                "title": "Thumbnail",
            },
            "qlk-cog": {
                "href": "https://example.invalid/qlk-cog.tif",
                "type": "image/tiff",
                "title": "Quicklook",
            },
        },
    }


def _picture(title: str) -> Image.Image:
    """A labeled gray frame. The words are the claim, not a radar return."""

    image = Image.new("L", (800, 480), color=32)
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 783, 463), outline=220, width=4)
    font = ImageFont.load_default(size=36)
    small = ImageFont.load_default(size=22)
    draw.text((48, 160), title, fill=235, font=font)
    draw.text((48, 230), "Demo placeholder", fill=210, font=small)
    draw.text((48, 270), "Not an ICEYE raster", fill=210, font=small)
    return image
