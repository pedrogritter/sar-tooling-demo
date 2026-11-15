"""The dwell player receives H.264 when the product file is mp4v."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from scene.jobs import MeasurementJobManager
from scene.paths import project_root
from scene.playback import PlaybackError, playable_mp4, sample_entry
from scene.web import dispatch

FAILURE = "The dwell video could not be prepared for playback."
DEMO = (
    project_root()
    / "demo"
    / "lisbon"
    / "scenes"
    / "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF"
    / "vid-mp4.mp4"
)


def _box(kind: bytes, payload: bytes) -> bytes:
    return (len(payload) + 8).to_bytes(4, "big") + kind + payload


def _mp4(fourcc: bytes) -> bytes:
    entry = _box(fourcc, b"\x00" * 8)
    stsd = _box(b"stsd", b"\x00\x00\x00\x00" + (1).to_bytes(4, "big") + entry)
    stbl = _box(b"stbl", stsd)
    minf = _box(b"minf", stbl)
    mdia = _box(b"mdia", minf)
    trak = _box(b"trak", mdia)
    moov = _box(b"moov", trak)
    ftyp = _box(b"ftyp", b"isom\x00\x00\x00\x00isom")
    mdat = _box(b"mdat", b"frames")
    return ftyp + mdat + moov


class SampleEntryTest(unittest.TestCase):
    def test_the_committed_dwell_video_is_mp4v(self) -> None:
        self.assertEqual(sample_entry(DEMO), "mp4v")

    def test_a_built_entry_is_read_from_the_end_of_the_file(self) -> None:
        self.assertEqual(sample_entry(_file(_mp4(b"mp4v"))), "mp4v")
        self.assertEqual(sample_entry(_file(_mp4(b"avc1"))), "avc1")
        self.assertIsNone(sample_entry(_file(b"not-an-mp4")))


class PlayableMp4Test(unittest.TestCase):
    def test_mp4v_is_replaced_for_the_player_and_the_product_stays(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            source = folder / "vid-mp4.mp4"
            original = _mp4(b"mp4v")
            source.write_bytes(original)

            calls = 0

            def transcode(src: Path, dest: Path) -> None:
                nonlocal calls
                calls += 1
                self.assertEqual(src, source)
                dest.write_bytes(b"AVC-PLAYABLE")

            with patch("scene.playback.ffmpeg_transcode", transcode):
                playable = playable_mp4(source)
                again = playable_mp4(source)
            self.assertEqual(calls, 1)
            self.assertEqual(playable.name, "vid-mp4.mp4.avc.mp4")
            self.assertEqual(playable.read_bytes(), b"AVC-PLAYABLE")
            self.assertEqual(again, playable)
            self.assertEqual(source.read_bytes(), original)

    def test_avc1_and_plain_bytes_are_not_transcoded(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            avc = folder / "vid-mp4.mp4"
            avc.write_bytes(_mp4(b"avc1"))
            plain = folder / "clip.mp4"
            plain.write_bytes(b"not-an-mp4")

            def transcode(src: Path, dest: Path) -> None:
                raise AssertionError(src.name)

            with patch("scene.playback.ffmpeg_transcode", transcode):
                self.assertEqual(playable_mp4(avc), avc)
                self.assertEqual(playable_mp4(plain), plain)

    def test_a_failed_transcode_uses_the_fixed_sentence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "vid-mp4.mp4"
            source.write_bytes(_mp4(b"mp4v"))

            def transcode(src: Path, dest: Path) -> None:
                raise PlaybackError(FAILURE)

            with patch("scene.playback.ffmpeg_transcode", transcode):
                with self.assertRaises(PlaybackError) as caught:
                    playable_mp4(source)
        self.assertEqual(str(caught.exception), FAILURE)

    def test_a_second_caller_waits_for_the_transcode(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "vid-mp4.mp4"
            source.write_bytes(_mp4(b"mp4v"))
            calls = 0
            entered = threading.Event()
            release = threading.Event()

            def transcode(src: Path, dest: Path) -> None:
                nonlocal calls
                calls += 1
                entered.set()
                self.assertTrue(release.wait(timeout=2))
                dest.write_bytes(b"AVC-PLAYABLE")

            results: list[Path] = []

            def run() -> None:
                results.append(playable_mp4(source))

            first = threading.Thread(target=run)
            second = threading.Thread(target=run)
            with patch("scene.playback.ffmpeg_transcode", transcode):
                first.start()
                self.assertTrue(entered.wait(timeout=2))
                second.start()
                release.set()
                first.join(timeout=2)
                second.join(timeout=2)
            self.assertEqual(calls, 1)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].read_bytes(), b"AVC-PLAYABLE")
            self.assertEqual(results[1], results[0])


class VideoRouteTest(unittest.TestCase):
    def test_the_route_serves_the_playable_file_not_the_dwell_stack(self) -> None:
        mp4 = _mp4(b"mp4v")
        cog = b"vid-cog-must-not-be-served"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scene_id = "ICEYE_VIDEO_20251024T135309Z_1_X52_SLF"
            folder = root / "scenes" / scene_id
            folder.mkdir(parents=True)
            payload = {
                "id": scene_id,
                "bbox": [-9.2, 38.6, -9.1, 38.7],
                "properties": {
                    "datetime": "2025-10-24T13:53:16.995Z",
                    "start_datetime": "2025-10-24T13:53:09.803Z",
                    "end_datetime": "2025-10-24T13:53:24.188Z",
                    "platform": "ICEYE-X52",
                    "sar:instrument_mode": "spotlight",
                    "sar:frequency_band": "X",
                    "sar:polarizations": ["VV"],
                    "sat:orbit_state": "descending",
                    "view:incidence_angle": 32.0,
                },
                "assets": {
                    "vid-mp4": {
                        "href": "https://example.invalid/vid-mp4.mp4",
                        "type": "video/mp4",
                    },
                    "vid-cog": {
                        "href": "https://example.invalid/vid-cog.tif",
                        "type": "image/tiff",
                    },
                },
            }
            (folder / "stac.json").write_text(json.dumps(payload), encoding="utf-8")
            (folder / "vid-mp4.mp4").write_bytes(mp4)
            (folder / "vid-cog.tif").write_bytes(cog)

            def transcode(src: Path, dest: Path) -> None:
                dest.write_bytes(b"AVC-PLAYABLE")

            manager = MeasurementJobManager(output_dir=folder)
            with (
                patch("scene.web.scene_dir", lambda scene: root / "scenes" / scene),
                patch("scene.playback.ffmpeg_transcode", transcode),
            ):
                response = dispatch(
                    "GET",
                    f"/api/scenes/{scene_id}/video",
                    b"",
                    None,  # type: ignore[arg-type]
                    manager,
                )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "video/mp4")
        self.assertEqual(response.body, b"AVC-PLAYABLE")
        self.assertNotIn(cog, response.body)
        self.assertIn(("Accept-Ranges", "bytes"), response.headers)


def _file(payload: bytes) -> Path:
    handle = tempfile.NamedTemporaryFile(delete=False)
    path = Path(handle.name)
    handle.write(payload)
    handle.close()
    return path