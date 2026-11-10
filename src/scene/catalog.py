"""Search index for the ICEYE open-data STAC collection.

The public bucket is a static catalog, not a STAC API. One collection
document lists every item. This module turns those links into records
the page can filter immediately, then fills bbox, mode, and thumbnail
from each item JSON in the background. The cache is ``data/catalog-index.json``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from .paths import catalog_index_path, valid_scene_id

COLLECTION_URL = (
    "https://iceye-open-data-catalog.s3.amazonaws.com/collections/iceye-sar.json"
)
ALLOWED_HOSTS = frozenset(
    {
        "iceye-open-data-catalog.s3.amazonaws.com",
        "iceye-open-data-catalog.s3-us-west-2.amazonaws.com",
    }
)
PREVIEW_KEYS = ("graphic", "qlk-cog", "qlk-json", "vid-mp4")
LARGE_KEYS = frozenset(
    {"grd-cog", "csi-cog", "vid-cog", "slc-cog", "cphd", "sicd", "sidd"}
)
CACHE_TTL = timedelta(hours=24)
_PAGE_SIZE = 24
_WORKERS = 4
_FAILURE_LIMIT = 2

JsonFetcher = Callable[[str], object]
BytesFetcher = Callable[[str], tuple[str, bytes]]
SizeFetcher = Callable[[str], int]
Clock = Callable[[], datetime]


class CatalogError(Exception):
    """The open-data collection or an item could not be read."""


@dataclass(frozen=True)
class CatalogAsset:
    """One asset href from a cached STAC item. The client sees the key, not the URL."""

    key: str
    href: str
    title: str
    media_type: str
    roles: tuple[str, ...]


@dataclass
class CatalogRecord:
    """One collection link, plus the fields filled in after its item JSON is read."""

    scene_id: str
    href: str
    acquired_at: str | None
    satellite: str | None
    product_code: str | None
    cached: bool = False
    mode: str | None = None
    incidence_angle: float | None = None
    bbox: tuple[float, float, float, float] | None = None
    thumbnail_href: str | None = None
    assets: tuple[CatalogAsset, ...] = ()


@dataclass(frozen=True)
class SearchQuery:
    """Filters the page sends. Empty strings mean the filter is off."""

    q: str = ""
    start: str | None = None
    end: str | None = None
    satellite: str | None = None
    product: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    limit: int = _PAGE_SIZE
    offset: int = 0


@dataclass(frozen=True)
class SearchResult:
    """One page of records, plus how far the background index has got."""

    items: tuple[CatalogRecord, ...]
    total: int
    offset: int
    limit: int
    indexed: int
    record_count: int
    indexing: bool
    unread_for_bbox: int
    satellites: tuple[str, ...]
    products: tuple[str, ...]


def allowed_https_url(url: str) -> bool:
    """True for HTTPS URLs on the public ICEYE open-data bucket."""

    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    return parsed.hostname in ALLOWED_HOSTS


def parse_scene_id(scene_id: str) -> tuple[str | None, str | None, str | None]:
    """Pull acquisition start, satellite, and product code out of an item id.

    Ids that do not match the ICEYE pattern still list. Their fields stay empty.
    The stamp is the acquisition start encoded in the id, not ``properties.datetime``.
    """

    import re

    match = re.fullmatch(
        r"ICEYE_[A-Z0-9]+_(?P<stamp>\d{8}T\d{6}Z)_\d+_(?P<satellite>X\d+)_(?P<product>[A-Z0-9]+)",
        scene_id,
    )
    if match is None:
        return None, None, None
    stamp = match.group("stamp")
    acquired = (
        f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}T"
        f"{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}Z"
    )
    return acquired, match.group("satellite"), match.group("product")


def is_large_asset(key: str, roles: tuple[str, ...]) -> bool:
    """Large rasters stay unchecked. The preview pack is the default download."""

    if key in LARGE_KEYS:
        return True
    if key in PREVIEW_KEYS:
        return False
    return "data" in roles


def default_asset_keys(assets: tuple[CatalogAsset, ...]) -> list[str]:
    """Preview pack keys that this item actually publishes."""

    present = {asset.key for asset in assets}
    return [key for key in PREVIEW_KEYS if key in present]


def filter_records(
    records: list[CatalogRecord], query: SearchQuery
) -> tuple[tuple[CatalogRecord, ...], int, int]:
    """Apply the fast filters, then bbox only where an item JSON is already cached.

    Returns the page, the match count, and how many fast-filter matches still
    have no cached footprint. That last number is zero when bbox is unset.
    """

    start = _bound(query.start, end=False)
    end = _bound(query.end, end=True)
    needle = query.q.casefold().strip()
    satellite = (query.satellite or "").casefold().strip()
    product = (query.product or "").casefold().strip()
    matched: list[CatalogRecord] = []
    unread = 0
    for record in records:
        if needle and needle not in record.scene_id.casefold():
            continue
        if satellite and (record.satellite or "").casefold() != satellite:
            continue
        if product and (record.product_code or "").casefold() != product:
            continue
        if start or end:
            if record.acquired_at is None:
                continue
            if start and record.acquired_at < start:
                continue
            if end and record.acquired_at > end:
                continue
        if query.bbox is not None:
            if not record.cached or record.bbox is None:
                unread += 1
                continue
            if not _intersects(record.bbox, query.bbox):
                continue
        matched.append(record)
    matched.sort(key=_newest_first)
    total = len(matched)
    offset = max(0, query.offset)
    limit = min(100, max(1, query.limit))
    page = tuple(matched[offset : offset + limit])
    return page, total, unread


def record_public(record: CatalogRecord, on_disk: bool) -> dict[str, object]:
    """JSON for one search row. The thumbnail URL is local."""

    thumbnail = (
        f"/api/catalog/items/{record.scene_id}/thumbnail"
        if record.thumbnail_href
        else None
    )
    return {
        "scene_id": record.scene_id,
        "acquired_at": record.acquired_at,
        "satellite": record.satellite,
        "product_code": record.product_code,
        "mode": record.mode,
        "incidence_angle": record.incidence_angle,
        "bbox": list(record.bbox) if record.bbox is not None else None,
        "cached": record.cached,
        "thumbnail_url": thumbnail,
        "on_disk": on_disk,
    }


class CatalogService:
    """Own the collection list, the item cache, and the background enricher."""

    def __init__(
        self,
        index_path: Path | None = None,
        fetch_json: JsonFetcher | None = None,
        fetch_bytes: BytesFetcher | None = None,
        head_size: SizeFetcher | None = None,
        now: Clock | None = None,
        auto_enrich: bool = True,
    ) -> None:
        self._index_path = index_path or catalog_index_path()
        self._fetch_json = fetch_json or http_get_json
        self._fetch_bytes = fetch_bytes or http_get_bytes
        self._head_size = head_size or http_head_size
        self._now = now or (lambda: datetime.now(UTC))
        self._auto_enrich = auto_enrich
        self._lock = threading.Lock()
        self._records: dict[str, CatalogRecord] = {}
        self._items: dict[str, dict[str, object]] = {}
        self._failures: dict[str, int] = {}
        self._priority: list[str] = []
        self._fetched_at: datetime | None = None
        self._indexing = False
        self._generation = 0
        self._worker: threading.Thread | None = None

    def ensure_ready(self) -> None:
        """Load a fresh disk cache or the collection document, then keep indexing."""

        with self._lock:
            ready = bool(self._records) and not self._stale_locked()
            generation = self._generation
        if not ready and not self._load_fresh_disk(generation):
            self._load_collection(generation)
        if self._auto_enrich:
            self.kick()

    def refresh(self) -> None:
        """Drop the 24-hour cache and read the collection again."""

        with self._lock:
            self._generation += 1
            generation = self._generation
            self._records = {}
            self._items = {}
            self._failures = {}
            self._priority = []
            self._fetched_at = None
            self._indexing = True
        self._index_path.unlink(missing_ok=True)
        self._load_collection(generation)
        if self._auto_enrich:
            self.kick()

    def kick(self) -> None:
        """Start the enricher when any record still needs its item JSON."""

        if not self._auto_enrich:
            return
        with self._lock:
            generation = self._generation
            if self._worker is not None and self._worker.is_alive():
                return
            if not any(not record.cached for record in self._records.values()):
                self._indexing = False
                return
            self._indexing = True
            worker = threading.Thread(
                target=self._enrich,
                args=(generation,),
                daemon=True,
                name="catalog-index",
            )
            self._worker = worker
        worker.start()

    def prioritize(self, scene_ids: list[str]) -> None:
        """Read the visible page before the rest of the collection."""

        with self._lock:
            for scene_id in reversed(scene_ids):
                if scene_id in self._priority:
                    self._priority.remove(scene_id)
                self._priority.insert(0, scene_id)

    def search(self, query: SearchQuery) -> SearchResult:
        with self._lock:
            records = [_snapshot(record) for record in self._records.values()]
            indexing = self._indexing
        page, total, unread = filter_records(records, query)
        satellites = tuple(
            sorted({record.satellite for record in records if record.satellite})
        )
        products = tuple(
            sorted({record.product_code for record in records if record.product_code})
        )
        indexed = sum(1 for record in records if record.cached)
        limit = min(100, max(1, query.limit))
        return SearchResult(
            items=page,
            total=total,
            offset=max(0, query.offset),
            limit=limit,
            indexed=indexed,
            record_count=len(records),
            indexing=indexing,
            unread_for_bbox=unread,
            satellites=satellites,
            products=products,
        )

    def enrich_item(self, scene_id: str) -> CatalogRecord:
        """Fetch one item JSON now. Used by download and the item route."""

        self.ensure_ready()
        with self._lock:
            record = self._records.get(scene_id)
            have_item = scene_id in self._items
        if record is None:
            raise KeyError(scene_id)
        if record.cached and have_item:
            return _snapshot(record)
        payload = self._fetch_json(record.href)
        with self._lock:
            self._apply_item_locked(scene_id, payload)
            self._save_locked()
            applied = self._records.get(scene_id)
        if applied is None:
            raise KeyError(scene_id)
        return _snapshot(applied)

    def full_item(self, scene_id: str) -> dict[str, object]:
        """STAC item object to write as ``stac.json``. Fetches when memory is cold."""

        self.ensure_ready()
        self.enrich_item(scene_id)
        with self._lock:
            item = self._items.get(scene_id)
        if item is None:
            raise KeyError(scene_id)
        return item

    def thumbnail(self, scene_id: str) -> tuple[str, bytes]:
        """Proxy the allowlisted thumbnail. The client never supplies the URL."""

        self.ensure_ready()
        record = self.enrich_item(scene_id)
        href = record.thumbnail_href
        if not href or not allowed_https_url(href):
            raise KeyError(scene_id)
        return self._fetch_bytes(href)

    def asset_sizes(self, assets: tuple[CatalogAsset, ...]) -> dict[str, int | None]:
        """HEAD each asset. A failed HEAD leaves that size unknown."""

        def one(asset: CatalogAsset) -> tuple[str, int | None]:
            if not allowed_https_url(asset.href):
                return asset.key, None
            try:
                return asset.key, self._head_size(asset.href)
            except (CatalogError, OSError, TimeoutError, ValueError):
                return asset.key, None

        if not assets:
            return {}
        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            return dict(pool.map(one, assets))

    def _load_fresh_disk(self, generation: int) -> bool:
        path = self._index_path
        if not path.is_file():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        fetched_at = _parse_time(_field(payload, "fetched_at"))
        if fetched_at is None or self._now() - fetched_at > CACHE_TTL:
            return False
        records = _records_from_disk(payload)
        with self._lock:
            if generation != self._generation:
                return False
            self._records = {record.scene_id: record for record in records}
            self._fetched_at = fetched_at
        return True

    def _load_collection(self, generation: int) -> None:
        payload = self._fetch_json(COLLECTION_URL)
        fresh = records_from_collection(payload)
        if not fresh:
            raise CatalogError("Open-data collection has no item links")
        now = self._now()
        with self._lock:
            if generation != self._generation:
                return
            previous = self._records
            merged: dict[str, CatalogRecord] = {}
            for record in fresh:
                old = previous.get(record.scene_id)
                if old is not None and old.cached and old.href == record.href:
                    merged[record.scene_id] = old
                else:
                    merged[record.scene_id] = record
            self._records = merged
            self._fetched_at = now
            self._save_locked()

    def _enrich(self, generation: int) -> None:
        while True:
            if not self._same_generation(generation):
                return
            batch = self._next_ids()
            if not batch:
                with self._lock:
                    if generation == self._generation:
                        self._indexing = False
                return
            with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
                fetched = list(pool.map(self._fetch_item_safe, batch))
            with self._lock:
                if generation != self._generation:
                    return
                for scene_id, payload in fetched:
                    if payload is None:
                        self._failures[scene_id] = self._failures.get(scene_id, 0) + 1
                        continue
                    self._apply_item_locked(scene_id, payload)
                self._save_locked()

    def _fetch_item_safe(self, scene_id: str) -> tuple[str, object | None]:
        with self._lock:
            record = self._records.get(scene_id)
        if record is None:
            return scene_id, None
        try:
            return scene_id, self._fetch_json(record.href)
        except (CatalogError, OSError, TimeoutError, ValueError):
            return scene_id, None

    def _next_ids(self) -> list[str]:
        with self._lock:
            pending = [
                scene_id
                for scene_id, record in self._records.items()
                if not record.cached
                and self._failures.get(scene_id, 0) < _FAILURE_LIMIT
            ]
            ordered: list[str] = []
            for scene_id in self._priority:
                if scene_id in pending and scene_id not in ordered:
                    ordered.append(scene_id)
            for scene_id in pending:
                if scene_id not in ordered:
                    ordered.append(scene_id)
            return ordered[:_WORKERS]

    def _same_generation(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _apply_item_locked(self, scene_id: str, payload: object) -> None:
        record = self._records.get(scene_id)
        if record is None or not isinstance(payload, dict):
            return
        enriched = enrich_record(record, payload)
        self._records[scene_id] = enriched
        self._items[scene_id] = payload
        self._failures.pop(scene_id, None)

    def _save_locked(self) -> None:
        path = self._index_path
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "fetched_at": None
            if self._fetched_at is None
            else self._fetched_at.isoformat(),
            "records": [_record_to_json(record) for record in self._records.values()],
        }
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(body), encoding="utf-8")
        temporary.replace(path)

    def _stale_locked(self) -> bool:
        if self._fetched_at is None:
            return True
        return self._now() - self._fetched_at > CACHE_TTL


def records_from_collection(payload: object) -> list[CatalogRecord]:
    """Read ``rel=item`` links. Relative hrefs resolve against the collection URL."""

    links = _field(payload, "links")
    if not isinstance(links, list):
        raise CatalogError("Collection links must be a list")
    records: list[CatalogRecord] = []
    seen: set[str] = set()
    for link in links:
        if not isinstance(link, dict) or link.get("rel") != "item":
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue
        absolute = urljoin(COLLECTION_URL, href)
        if not allowed_https_url(absolute):
            continue
        title = link.get("title")
        stem = Path(urlsplit(absolute).path).stem
        scene_id = title if isinstance(title, str) and title else stem
        if not valid_scene_id(scene_id) or scene_id in seen:
            continue
        seen.add(scene_id)
        acquired, satellite, product = parse_scene_id(scene_id)
        records.append(
            CatalogRecord(
                scene_id=scene_id,
                href=absolute,
                acquired_at=acquired,
                satellite=satellite,
                product_code=product,
            )
        )
    return records


def enrich_record(record: CatalogRecord, payload: dict[str, object]) -> CatalogRecord:
    """Copy search fields from one STAC item onto its collection record."""

    properties = payload.get("properties")
    mode = None
    incidence = None
    if isinstance(properties, dict):
        raw_mode = properties.get("sar:instrument_mode")
        if isinstance(raw_mode, str) and raw_mode:
            mode = raw_mode
        raw_angle = properties.get("view:incidence_angle")
        if isinstance(raw_angle, (int, float)) and not isinstance(raw_angle, bool):
            incidence = float(raw_angle)
    assets = _assets_from_item(payload.get("assets"))
    return CatalogRecord(
        scene_id=record.scene_id,
        href=record.href,
        acquired_at=record.acquired_at,
        satellite=record.satellite,
        product_code=record.product_code,
        cached=True,
        mode=mode,
        incidence_angle=incidence,
        bbox=_bbox(payload.get("bbox")),
        thumbnail_href=_thumbnail_href(payload, assets),
        assets=assets,
    )


def http_get_json(url: str) -> object:
    """GET a JSON document and refuse a redirect off the open-data bucket."""

    if not allowed_https_url(url):
        raise CatalogError("URL is not on the ICEYE open-data bucket")
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            final = response.geturl()
            if not allowed_https_url(final):
                raise CatalogError("Redirect left the ICEYE open-data bucket")
            return json.load(response)
    except CatalogError:
        raise
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise CatalogError(f"Could not read {url}: {exc}") from exc


def http_get_bytes(url: str) -> tuple[str, bytes]:
    """GET a thumbnail. Same host allowlist as the JSON reader."""

    if not allowed_https_url(url):
        raise CatalogError("Thumbnail URL is not on the ICEYE open-data bucket")
    request = Request(url, headers={"Accept": "image/*,*/*"})
    try:
        with urlopen(request, timeout=60) as response:
            final = response.geturl()
            if not allowed_https_url(final):
                raise CatalogError("Redirect left the ICEYE open-data bucket")
            content_type = response.headers.get_content_type()
            return content_type, response.read()
    except CatalogError:
        raise
    except (OSError, TimeoutError) as exc:
        raise CatalogError(f"Could not read thumbnail {url}: {exc}") from exc


def http_head_size(url: str) -> int:
    """Content-Length for one asset. Zero when the origin omits it."""

    if not allowed_https_url(url):
        raise CatalogError("Asset URL is not on the ICEYE open-data bucket")
    request = Request(url, method="HEAD")
    try:
        with urlopen(request, timeout=30) as response:
            if not allowed_https_url(response.geturl()):
                raise CatalogError("Redirect left the ICEYE open-data bucket")
            return int(response.headers.get("Content-Length") or 0)
    except CatalogError:
        raise
    except (OSError, TimeoutError, ValueError) as exc:
        raise CatalogError(f"Could not size {url}: {exc}") from exc


_DEFAULT: CatalogService | None = None


def default_catalog() -> CatalogService:
    """Process-wide catalog. The first search loads or builds the index."""

    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = CatalogService()
    return _DEFAULT


def _snapshot(record: CatalogRecord) -> CatalogRecord:
    return CatalogRecord(
        scene_id=record.scene_id,
        href=record.href,
        acquired_at=record.acquired_at,
        satellite=record.satellite,
        product_code=record.product_code,
        cached=record.cached,
        mode=record.mode,
        incidence_angle=record.incidence_angle,
        bbox=record.bbox,
        thumbnail_href=record.thumbnail_href,
        assets=record.assets,
    )


def _newest_first(record: CatalogRecord) -> tuple[int, str, str]:
    # Undated ids sort after every real acquisition. The time string is
    # inverted by the leading 0/1 and a descending ISO sort via a prefix.
    if record.acquired_at is None:
        return (1, "", record.scene_id)
    return (0, _invert_stamp(record.acquired_at), record.scene_id)


def _invert_stamp(stamp: str) -> str:
    """Lexicographic order that puts a later UTC timestamp first."""

    inverted: list[str] = []
    for char in stamp:
        if char.isdigit():
            inverted.append(chr(ord("9") - ord(char) + ord("0")))
        else:
            inverted.append(char)
    return "".join(inverted)


def _bound(value: str | None, end: bool) -> str | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    import re

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return f"{text}T23:59:59Z" if end else f"{text}T00:00:00Z"
    return text


def _intersects(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    west, south, east, north = left
    other_west, other_south, other_east, other_north = right
    separated = (
        east < other_west
        or other_east < west
        or north < other_south
        or other_north < south
    )
    return not separated


def _bbox(raw: object) -> tuple[float, float, float, float] | None:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    if any(_not_number(value) for value in raw):
        return None
    west, south, east, north = (float(value) for value in raw)
    if west >= east or south >= north:
        return None
    return west, south, east, north


def _not_number(value: object) -> bool:
    return not isinstance(value, (int, float)) or isinstance(value, bool)


def _assets_from_item(raw: object) -> tuple[CatalogAsset, ...]:
    if not isinstance(raw, dict):
        return ()
    assets: list[CatalogAsset] = []
    for key, value in raw.items():
        if not isinstance(key, str) or not key or not isinstance(value, dict):
            continue
        href = value.get("href")
        if not isinstance(href, str) or not href:
            continue
        title = value.get("title")
        media = value.get("type")
        roles_raw = value.get("roles")
        roles: tuple[str, ...] = ()
        if isinstance(roles_raw, list):
            roles = tuple(role for role in roles_raw if isinstance(role, str) and role)
        assets.append(
            CatalogAsset(
                key=key,
                href=href,
                title=title if isinstance(title, str) and title else key,
                media_type=media if isinstance(media, str) else "",
                roles=roles,
            )
        )
    return tuple(assets)


def _thumbnail_href(
    payload: dict[str, object], assets: tuple[CatalogAsset, ...]
) -> str | None:
    for asset in assets:
        if asset.key == "graphic" and allowed_https_url(asset.href):
            return asset.href
    links = payload.get("links")
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict) or link.get("rel") != "thumbnail":
                continue
            href = link.get("href")
            if isinstance(href, str) and allowed_https_url(href):
                title = link.get("title")
                if title == "Thumbnail" or link.get("type") == "image/png":
                    return href
        for link in links:
            if not isinstance(link, dict) or link.get("rel") != "thumbnail":
                continue
            href = link.get("href")
            if isinstance(href, str) and allowed_https_url(href):
                return href
    return None


def _records_from_disk(payload: object) -> list[CatalogRecord]:
    raw_records = _field(payload, "records")
    if not isinstance(raw_records, list):
        return []
    records: list[CatalogRecord] = []
    for raw in raw_records:
        record = _record_from_json(raw)
        if record is not None:
            records.append(record)
    return records


def _record_from_json(raw: object) -> CatalogRecord | None:
    if not isinstance(raw, dict):
        return None
    scene_id = raw.get("scene_id")
    href = raw.get("href")
    if not isinstance(scene_id, str) or not isinstance(href, str):
        return None
    assets_raw = raw.get("assets")
    assets: list[CatalogAsset] = []
    if isinstance(assets_raw, list):
        for item in assets_raw:
            asset = _asset_from_json(item)
            if asset is not None:
                assets.append(asset)
    bbox = _bbox(raw.get("bbox"))
    incidence = raw.get("incidence_angle")
    return CatalogRecord(
        scene_id=scene_id,
        href=href,
        acquired_at=_optional_str(raw.get("acquired_at")),
        satellite=_optional_str(raw.get("satellite")),
        product_code=_optional_str(raw.get("product_code")),
        cached=raw.get("cached") is True,
        mode=_optional_str(raw.get("mode")),
        incidence_angle=(
            float(incidence)
            if isinstance(incidence, (int, float)) and not isinstance(incidence, bool)
            else None
        ),
        bbox=bbox,
        thumbnail_href=_optional_str(raw.get("thumbnail_href")),
        assets=tuple(assets),
    )


def _asset_from_json(raw: object) -> CatalogAsset | None:
    if not isinstance(raw, dict):
        return None
    key = raw.get("key")
    href = raw.get("href")
    if not isinstance(key, str) or not isinstance(href, str):
        return None
    roles_raw = raw.get("roles")
    roles: tuple[str, ...] = ()
    if isinstance(roles_raw, list):
        roles = tuple(role for role in roles_raw if isinstance(role, str))
    title = raw.get("title")
    media = raw.get("media_type")
    return CatalogAsset(
        key=key,
        href=href,
        title=title if isinstance(title, str) else key,
        media_type=media if isinstance(media, str) else "",
        roles=roles,
    )


def _record_to_json(record: CatalogRecord) -> dict[str, object]:
    return {
        "scene_id": record.scene_id,
        "href": record.href,
        "acquired_at": record.acquired_at,
        "satellite": record.satellite,
        "product_code": record.product_code,
        "cached": record.cached,
        "mode": record.mode,
        "incidence_angle": record.incidence_angle,
        "bbox": list(record.bbox) if record.bbox is not None else None,
        "thumbnail_href": record.thumbnail_href,
        "assets": [
            {
                "key": asset.key,
                "href": asset.href,
                "title": asset.title,
                "media_type": asset.media_type,
                "roles": list(asset.roles),
            }
            for asset in record.assets
        ],
    }


def _field(payload: object, key: str) -> object:
    if isinstance(payload, dict):
        return payload.get(key)
    return None


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed

