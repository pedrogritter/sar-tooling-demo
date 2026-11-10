"""Catalog filters run on a fixture collection. Nothing here calls S3."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scene.catalog import (
    COLLECTION_URL,
    CatalogError,
    CatalogService,
    SearchQuery,
    parse_scene_id,
)

LISBON = "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF"
OTHER = "ICEYE_6Q31WW_20251110T182058Z_7010715_X56_SLEDF"
HOST = "https://iceye-open-data-catalog.s3.amazonaws.com"


class ParseIdTest(unittest.TestCase):
    def test_known_pattern_and_unknown_id(self) -> None:
        acquired, satellite, product = parse_scene_id(OTHER)
        self.assertEqual(acquired, "2025-11-10T18:20:58Z")
        self.assertEqual(satellite, "X56")
        self.assertEqual(product, "SLEDF")
        self.assertEqual(parse_scene_id("custom-scene"), (None, None, None))


class SearchTest(unittest.TestCase):
    def test_filters_paging_and_unread_footprints(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            service = _service(Path(raw))
            service.ensure_ready()
            service.enrich_item(LISBON)

            newest = service.search(SearchQuery(limit=1))
            self.assertEqual(newest.items[0].scene_id, OTHER)
            self.assertEqual(newest.total, 3)
            self.assertFalse(newest.items[0].cached)

            text = service.search(SearchQuery(q="6q31ww"))
            self.assertEqual([item.scene_id for item in text.items], [OTHER])

            november = service.search(SearchQuery(start="2025-11-01", end="2025-11-30"))
            self.assertEqual([item.scene_id for item in november.items], [OTHER])

            satellite = service.search(SearchQuery(satellite="x52"))
            self.assertEqual([item.scene_id for item in satellite.items], [LISBON])

            footprint = service.search(
                SearchQuery(bbox=(-10.0, 38.0, -9.0, 39.0))
            )
            self.assertEqual([item.scene_id for item in footprint.items], [LISBON])
            self.assertEqual(footprint.unread_for_bbox, 2)
            self.assertEqual(footprint.indexed, 1)

            unknown = service.search(SearchQuery(q="custom-scene"))
            self.assertIsNone(unknown.items[0].satellite)
            self.assertIsNone(unknown.items[0].acquired_at)

    def test_thumbnail_refuses_a_foreign_host(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            service = _service(Path(raw), graphic_href="https://evil.example/thumb.png")
            service.ensure_ready()
            with self.assertRaises(KeyError):
                service.thumbnail(LISBON)

    def test_refresh_rebuilds_after_the_cache_is_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            service = _service(root)
            service.ensure_ready()
            service.enrich_item(OTHER)
            self.assertTrue((root / "index.json").is_file())
            service.refresh()
            again = service.search(SearchQuery(q=OTHER))
            self.assertEqual(again.indexed, 0)
            self.assertFalse(again.items[0].cached)


def _service(root: Path, graphic_href: str | None = None) -> CatalogService:
    href = graphic_href or f"{HOST}/data/x/THM.png"

    def fetch_json(url: str) -> object:
        if url == COLLECTION_URL:
            return {
                "links": [
                    _link(LISBON),
                    _link(OTHER),
                    _link("custom-scene"),
                ]
            }
        scene_id = Path(url).stem
        bbox = {
            LISBON: [-9.2, 38.6, -9.1, 38.7],
            OTHER: [-77.1, -9.6, -77.0, -9.5],
        }.get(scene_id)
        return {
            "id": scene_id,
            "bbox": bbox,
            "properties": {
                "sar:instrument_mode": "spotlight",
                "view:incidence_angle": 29.5,
            },
            "assets": {
                "graphic": {
                    "href": href,
                    "title": "Thumbnail",
                    "type": "image/png",
                    "roles": ["graphic"],
                },
                "slc-cog": {
                    "href": f"{HOST}/data/x/SLC.tif",
                    "title": "SLC",
                    "type": "image/tiff",
                    "roles": ["data"],
                },
            },
        }

    return CatalogService(
        index_path=root / "index.json",
        fetch_json=fetch_json,
        fetch_bytes=lambda _url: ("image/png", b"png"),
        head_size=lambda _url: 12,
        auto_enrich=False,
    )


def _link(scene_id: str) -> dict[str, str]:
    return {
        "rel": "item",
        "href": f"{HOST}/stac-items/2025/11/{scene_id}.json",
        "title": scene_id,
        "type": "application/geo+json",
    }


class RejectedUrlTest(unittest.TestCase):
    def test_collection_without_items_fails(self) -> None:
        service = CatalogService(
            index_path=Path("/tmp/unused-catalog-index.json"),
            fetch_json=lambda _url: {"links": []},
            auto_enrich=False,
        )
        with self.assertRaises(CatalogError):
            service.ensure_ready()


if __name__ == "__main__":
    unittest.main()
