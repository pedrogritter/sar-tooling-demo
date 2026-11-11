"""Catalog filters run on a fixture collection. Nothing here calls S3."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scene.catalog import (
    COLLECTION_URL,
    LARGE_KEYS,
    PREVIEW_KEYS,
    CatalogAsset,
    CatalogError,
    CatalogService,
    SearchQuery,
    default_asset_keys,
    is_large_asset,
    parse_scene_id,
    record_public,
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

            footprint = service.search(SearchQuery(bbox=(-10.0, 38.0, -9.0, 39.0)))
            self.assertEqual([item.scene_id for item in footprint.items], [LISBON])
            self.assertEqual(footprint.items[0].place, "Lisbon")
            public = record_public(footprint.items[0], False)
            self.assertEqual(public["place"], "Lisbon")
            self.assertTrue(public["has_slc"])
            self.assertFalse(public["has_grd"])
            self.assertFalse(public["has_video"])
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

    def test_non_finite_footprint_does_not_match_a_search(self) -> None:
        with tempfile.TemporaryDirectory() as raw:

            def fetch_json(url: str) -> object:
                if url == COLLECTION_URL:
                    return {"links": [_link(LISBON)]}
                return {
                    "id": LISBON,
                    "bbox": [float("nan"), 0, 1, 1],
                    "properties": {"sar:instrument_mode": "spotlight"},
                    "assets": {
                        "graphic": {
                            "href": f"{HOST}/data/x/THM.png",
                            "title": "Thumbnail",
                            "type": "image/png",
                        }
                    },
                }

            service = CatalogService(
                index_path=Path(raw) / "index.json",
                fetch_json=fetch_json,
                auto_enrich=False,
            )
            service.ensure_ready()
            service.enrich_item(LISBON)
            found = service.search(SearchQuery(bbox=(10.0, 10.0, 11.0, 12.0)))
            self.assertEqual(found.items, ())
            self.assertEqual(found.unread_for_bbox, 1)


class PreviewPackTest(unittest.TestCase):
    def test_large_rasters_stay_out_of_the_default_download(self) -> None:
        self.assertTrue(LARGE_KEYS.isdisjoint(PREVIEW_KEYS))
        self.assertFalse(is_large_asset("graphic", ()))
        self.assertFalse(is_large_asset("qlk-cog", ("data",)))
        self.assertTrue(is_large_asset("slc-cog", ()))
        self.assertTrue(is_large_asset("custom-product", ("data",)))
        assets = (
            CatalogAsset("graphic", f"{HOST}/a.png", "Thumbnail", "image/png", ()),
            CatalogAsset("slc-cog", f"{HOST}/a.tif", "SLC", "image/tiff", ("data",)),
            CatalogAsset("qlk-cog", f"{HOST}/b.tif", "Quicklook", "image/tiff", ()),
        )
        self.assertEqual(default_asset_keys(assets), ["graphic", "qlk-cog"])


def _service(
    root: Path,
    graphic_href: str | None = None,
    extra_assets: dict[str, object] | None = None,
) -> CatalogService:
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
                **(extra_assets or {}),
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
