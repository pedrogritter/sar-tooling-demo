"""Flat data/ checkouts move into data/scenes/<id>/ without copying bytes."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scene.store import migrate_flat_scene

SCENE_ID = "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF"


class MigrateFlatSceneTest(unittest.TestCase):
    def test_rename_keeps_bytes_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "stac.json").write_text(json.dumps(_item()), encoding="utf-8")
            (root / "graphic.png").write_bytes(b"png")
            (root / "slc-cog.tif").write_bytes(b"slc-bytes")
            (root / "notes.txt").write_text("leave me", encoding="utf-8")

            destination = migrate_flat_scene(root)

            self.assertIsNotNone(destination)
            assert destination is not None
            self.assertEqual(destination.name, SCENE_ID)
            self.assertFalse((root / "stac.json").exists())
            self.assertEqual((destination / "graphic.png").read_bytes(), b"png")
            self.assertEqual((destination / "slc-cog.tif").read_bytes(), b"slc-bytes")
            self.assertEqual(
                (root / "notes.txt").read_text(encoding="utf-8"),
                "leave me",
            )
            self.assertIsNone(migrate_flat_scene(root))

    def test_listed_asset_that_is_missing_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "stac.json").write_text(json.dumps(_item()), encoding="utf-8")
            destination = migrate_flat_scene(root)
            self.assertIsNotNone(destination)
            assert destination is not None
            self.assertFalse((destination / "graphic.png").exists())
            self.assertFalse((destination / "slc-cog.tif").exists())
            self.assertTrue((destination / "stac.json").is_file())

    def test_unsafe_id_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            item = _item()
            item["id"] = "../escape"
            (root / "stac.json").write_text(json.dumps(item), encoding="utf-8")
            with self.assertRaises(ValueError):
                migrate_flat_scene(root)
            self.assertTrue((root / "stac.json").is_file())


def _item() -> dict[str, object]:
    return {
        "id": SCENE_ID,
        "assets": {
            "graphic": {"href": "https://example.test/thumb.png"},
            "slc-cog": {"href": "https://example.test/slc.tif"},
        },
    }


if __name__ == "__main__":
    unittest.main()
