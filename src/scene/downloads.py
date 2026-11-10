"""One download at a time, with a byte count for each file.

Progress is the size of the file curl is writing. The page polls that
size. curl's own progress bar is not parsed. A failed file keeps whatever
earlier files already landed in the scene folder.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .catalog import CatalogAsset, CatalogError, CatalogService, default_asset_keys
from .fetch import fetch as fetch_asset
from .fetch import remote_size as remote_content_length
from .naming import local_asset_name
from .paths import scene_dir, valid_scene_id

FileState = Literal["pending", "downloading", "done", "kept", "failed"]
JobStatus = Literal["idle", "running", "done", "failed"]
FetchFile = Callable[[str, Path], str]
RemoteSize = Callable[[str], int]


class DownloadError(Exception):
    """The request named an asset this item does not publish."""


class DownloadAlreadyRunningError(Exception):
    """A download is already in progress."""


@dataclass
class _File:
    key: str
    name: str
    href: str | None
    state: FileState
    bytes_done: int
    bytes_total: int
    path: Path


class DownloadManager:
    """Own the single download thread and the file list the page polls."""

    def __init__(
        self,
        catalog: CatalogService,
        fetch_file: FetchFile | None = None,
        remote_size: RemoteSize | None = None,
        scenes_root: Path | None = None,
    ) -> None:
        self._catalog = catalog
        self._fetch_file = fetch_file or fetch_asset
        self._remote_size = remote_size or remote_content_length
        self._scenes_root = scenes_root
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._status: JobStatus = "idle"
        self._job_id: str | None = None
        self._scene_id: str | None = None
        self._files: list[_File] = []
        self._error: str | None = None
        self._item: dict[str, object] | None = None

    def start(self, scene_id: str, assets: list[str] | None) -> str:
        """Queue one scene. ``assets`` None selects the preview pack."""

        if not valid_scene_id(scene_id):
            raise DownloadError(f"Invalid scene id: {scene_id}")
        try:
            item = self._catalog.full_item(scene_id)
            record = self._catalog.enrich_item(scene_id)
        except KeyError as exc:
            raise DownloadError(f"Unknown catalog item: {scene_id}") from exc
        except CatalogError as exc:
            raise DownloadError(str(exc)) from exc
        selected = _selected_keys(record.assets, assets)
        folder = self._folder(scene_id)
        files = [_stac_file(folder)]
        known = {asset.key: asset for asset in record.assets}
        for key in selected:
            asset = known[key]
            files.append(
                _File(
                    key=key,
                    name=local_asset_name(key, asset.href),
                    href=asset.href,
                    state="pending",
                    bytes_done=0,
                    bytes_total=0,
                    path=folder / local_asset_name(key, asset.href),
                )
            )
        with self._lock:
            if self._status == "running":
                raise DownloadAlreadyRunningError("A download is already running")
            job_id = uuid.uuid4().hex
            self._job_id = job_id
            self._status = "running"
            self._scene_id = scene_id
            self._files = files
            self._error = None
            self._item = item
            thread = threading.Thread(
                target=self._run,
                args=(job_id, folder),
                daemon=True,
                name=f"download-{job_id[:8]}",
            )
            self._thread = thread
        thread.start()
        return job_id

    def current(self) -> dict[str, object]:
        """Status snapshot. Byte counts for the active file come from disk."""

        with self._lock:
            files: list[dict[str, object]] = []
            for item in self._files:
                done = item.bytes_done
                if item.state == "downloading" and item.path.is_file():
                    done = item.path.stat().st_size
                files.append(
                    {
                        "key": item.key,
                        "name": item.name,
                        "state": item.state,
                        "bytes_done": done,
                        "bytes_total": item.bytes_total,
                    }
                )
            return {
                "status": self._status,
                "job_id": self._job_id,
                "scene_id": self._scene_id,
                "files": files,
                "error": self._error,
            }

    def _folder(self, scene_id: str) -> Path:
        if self._scenes_root is None:
            return scene_dir(scene_id)
        return self._scenes_root / scene_id

    def wait(self, timeout: float = 5) -> None:
        """Block until the worker exits. Tests use this."""

        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run(self, job_id: str, folder: Path) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            self._write_stac(job_id, folder)
            for index in range(1, self._file_count()):
                if not self._active(job_id):
                    return
                self._transfer(job_id, index)
        except Exception as exc:
            self._fail(job_id, _short(exc))
            return
        with self._lock:
            if self._job_id != job_id:
                return
            if self._status == "running":
                self._status = "done"
                self._error = None

    def _write_stac(self, job_id: str, folder: Path) -> None:
        with self._lock:
            if self._job_id != job_id:
                return
            target = self._files[0]
            item = self._item
            target.state = "downloading"
        if item is None:
            raise DownloadError("Catalog item JSON is missing")
        body = json.dumps(item, indent=2).encode("utf-8")
        path = folder / "stac.json"
        path.write_bytes(body)
        with self._lock:
            if self._job_id != job_id:
                return
            target = self._files[0]
            target.bytes_total = len(body)
            target.bytes_done = len(body)
            target.state = "done"
            target.path = path

    def _transfer(self, job_id: str, index: int) -> None:
        with self._lock:
            if self._job_id != job_id:
                return
            target = self._files[index]
            href = target.href
            path = target.path
            target.state = "downloading"
        if href is None:
            raise DownloadError(f"Missing href for {path.name}")
        try:
            total = self._remote_size(href)
        except (OSError, TimeoutError, ValueError) as exc:
            self._fail_file(job_id, index, _short(exc))
            raise
        with self._lock:
            if self._job_id == job_id:
                self._files[index].bytes_total = total
        try:
            result = self._fetch_file(href, path)
        except Exception as exc:
            self._fail_file(job_id, index, _short(exc))
            raise
        with self._lock:
            if self._job_id != job_id:
                return
            done = self._files[index]
            done.bytes_done = path.stat().st_size if path.is_file() else 0
            if done.bytes_total <= 0:
                done.bytes_total = done.bytes_done
            done.state = "kept" if result == "kept" else "done"

    def _fail_file(self, job_id: str, index: int, reason: str) -> None:
        with self._lock:
            if self._job_id != job_id:
                return
            self._files[index].state = "failed"
            self._status = "failed"
            self._error = reason

    def _fail(self, job_id: str, reason: str) -> None:
        with self._lock:
            if self._job_id != job_id or self._status != "running":
                return
            self._status = "failed"
            self._error = reason

    def _active(self, job_id: str) -> bool:
        with self._lock:
            return self._job_id == job_id and self._status == "running"

    def _file_count(self) -> int:
        with self._lock:
            return len(self._files)


def _selected_keys(
    assets: tuple[CatalogAsset, ...], requested: list[str] | None
) -> list[str]:
    known = {asset.key for asset in assets}
    if requested is None:
        return default_asset_keys(assets)
    if not requested:
        raise DownloadError("Choose at least one asset")
    chosen: list[str] = []
    for key in requested:
        if not isinstance(key, str) or not key:
            raise DownloadError("Asset keys must be strings")
        if key not in known:
            raise DownloadError(f"Unknown asset: {key}")
        if key not in chosen:
            chosen.append(key)
    return chosen


def _stac_file(folder: Path) -> _File:
    return _File(
        key="stac",
        name="stac.json",
        href=None,
        state="pending",
        bytes_done=0,
        bytes_total=0,
        path=folder / "stac.json",
    )


def _short(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return " ".join(text.split())[:500]


_DEFAULT: DownloadManager | None = None


def default_downloads() -> DownloadManager:
    """Process-wide download job. It shares the process catalog."""

    global _DEFAULT
    if _DEFAULT is None:
        from .catalog import default_catalog

        _DEFAULT = DownloadManager(default_catalog())
    return _DEFAULT
