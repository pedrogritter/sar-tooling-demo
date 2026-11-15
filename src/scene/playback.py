"""Make the dwell mp4 something the browser can decode.

The product file stays where it was downloaded. MPEG-4 Part 2 (``mp4v``)
is copied to H.264 beside it. ``vid-cog.tif`` is not read here.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

LOGGER = logging.getLogger("scene")
FAILURE = "The dwell video could not be prepared for playback."
_CONTAINERS = frozenset({b"moov", b"trak", b"mdia", b"minf", b"stbl"})


class PlaybackError(RuntimeError):
    """The player file could not be written. The text is safe to show."""


def sample_entry(path: Path) -> str | None:
    """The first sample-entry fourcc, or None when the file is not that mp4."""

    try:
        data = path.read_bytes()
    except OSError:
        return None
    found = _walk(data, 0, len(data))
    return found


def playable_mp4(source: Path) -> Path:
    """The file the video route should send for ``source``.

    A fresh ``mp4v`` cache is returned as-is. ``mp4v`` without a cache is
    transcoded. Every other file, including one with no sample entry, is
    the source path.
    """

    cache = source.with_name(source.name + ".avc.mp4")
    if _fresh(cache, source):
        return cache
    if sample_entry(source) != "mp4v":
        return source
    try:
        ffmpeg_transcode(source, cache)
    except PlaybackError:
        raise
    except OSError as exc:
        raise PlaybackError(FAILURE) from exc
    if not cache.is_file():
        raise PlaybackError(FAILURE)
    return cache


def ffmpeg_transcode(source: Path, dest: Path) -> None:
    """Write an H.264 faststart mp4. The source is not opened for writing."""

    if shutil.which("ffmpeg") is None:
        raise PlaybackError(FAILURE)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(dest.name + ".part")
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(temporary),
    ]
    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode != 0 or not temporary.is_file():
        temporary.unlink(missing_ok=True)
        detail = completed.stderr.decode("utf-8", "replace")[-500:]
        LOGGER.error("dwell video transcode failed: %s", detail)
        raise PlaybackError(FAILURE)
    temporary.replace(dest)


def _fresh(cache: Path, source: Path) -> bool:
    if not cache.is_file():
        return False
    try:
        return cache.stat().st_mtime_ns >= source.stat().st_mtime_ns
    except OSError:
        return False


def _walk(data: bytes, start: int, end: int) -> str | None:
    for offset, size, kind, header in _boxes(data, start, end):
        if kind == b"stsd":
            return _entry(data, offset + header, offset + size)
        if kind in _CONTAINERS:
            found = _walk(data, offset + header, offset + size)
            if found is not None:
                return found
    return None


def _boxes(
    data: bytes, start: int, end: int
) -> list[tuple[int, int, bytes, int]]:
    found: list[tuple[int, int, bytes, int]] = []
    cursor = start
    while cursor + 8 <= end:
        size = int.from_bytes(data[cursor : cursor + 4], "big")
        kind = data[cursor + 4 : cursor + 8]
        header = 8
        if size == 1:
            if cursor + 16 > end:
                break
            size = int.from_bytes(data[cursor + 8 : cursor + 16], "big")
            header = 16
        if size < header or cursor + size > end:
            break
        found.append((cursor, size, kind, header))
        cursor += size
    return found


def _entry(data: bytes, start: int, end: int) -> str | None:
    if start + 8 > end:
        return None
    count = int.from_bytes(data[start + 4 : start + 8], "big")
    entry = start + 8
    if count < 1 or entry + 8 > end:
        return None
    return data[entry + 4 : entry + 8].decode("latin1")