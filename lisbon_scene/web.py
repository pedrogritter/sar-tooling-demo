"""HTTP entry for the one-page scene viewer.

Routes are fixed. The process never serves the data directory, so a
request cannot read the dwell video or any other file by path.
"""

from __future__ import annotations

import json
import logging
import mimetypes
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from .jobs import JobAlreadyRunningError, MeasurementJobManager, default_manager
from .loader import SceneDataError, SceneRecord, load_scene
from .page import render_page

if TYPE_CHECKING:
    from .quicklook import QuicklookImage

LOGGER = logging.getLogger("lisbon_scene")
_MAX_CLIENT_ERROR_BYTES = 2048
_NOTE_NAME = "scene_note.md"
_IMMUTABLE_CACHE = "public, max-age=31536000, immutable"


@dataclass(frozen=True)
class AppState:
    """Everything the page needs, loaded once at startup."""

    scene: SceneRecord
    note_markdown: str
    quicklook: QuicklookImage | None
    static_files: dict[str, tuple[str, bytes]]


@dataclass(frozen=True)
class HttpResponse:
    status: int
    content_type: str
    body: bytes
    cache_control: str = "no-store"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def build_state(
    stac_path: Path | None = None,
    note_path: Path | None = None,
) -> AppState:
    """Load the scene, the note, the quicklook PNG, and the static files.

    A missing STAC record or an empty note stops startup. A missing
    quicklook does not: the page explains that ``scene.py`` has not
    saved it yet.
    """

    scene = load_scene(stac_path)
    note_file = note_path or (project_root() / _NOTE_NAME)
    note = _read_note(note_file)
    quicklook = _load_quicklook(scene)
    static_files = _load_static(project_root() / "static")
    return AppState(
        scene=scene,
        note_markdown=note,
        quicklook=quicklook,
        static_files=static_files,
    )


def dispatch(
    method: str,
    target: str,
    body: bytes,
    state: AppState,
    job_manager: MeasurementJobManager | None = None,
) -> HttpResponse:
    """Answer one request. Unknown paths and methods get a short error."""

    manager = job_manager or default_manager()
    path = urlsplit(target).path
    if method == "GET" and path == "/":
        index = _ui_dist_dir() / "index.html"
        if index.is_file():
            return _file_response(index, "text/html; charset=utf-8")
        quicklook = state.quicklook
        page = render_page(
            state.scene,
            state.note_markdown,
            None if quicklook is None else quicklook.width,
            None if quicklook is None else quicklook.height,
        )
        return HttpResponse(200, "text/html; charset=utf-8", page.encode("utf-8"))
    if method == "GET" and path == "/api/scene":
        return _json(200, _scene_payload(state, manager))
    if method == "GET" and path == "/api/jobs/current":
        return _json(200, manager.current().to_public())
    if method == "GET" and path == "/overview.png":
        overview = manager.output_dir / "overview.png"
        if not overview.is_file():
            return _plain(404, "Overview is not on disk")
        return _file_response(overview, "image/png")
    if method == "GET" and path == "/quicklook.png":
        if state.quicklook is None:
            return _plain(404, "Quicklook is not on disk. Run python3 scene.py")
        return HttpResponse(200, "image/png", state.quicklook.png)
    if method == "GET" and path in state.static_files:
        content_type, payload = state.static_files[path]
        return HttpResponse(200, content_type, payload)
    if method == "GET":
        dist_response = _dist_asset_response(path)
        if dist_response is not None:
            return dist_response
    if method == "POST" and path == "/api/jobs/measure":
        if body:
            return _plain(400, "Measure job request body must be empty")
        try:
            job_id = manager.start()
        except JobAlreadyRunningError:
            return _json(409, {"status": "running"})
        return _json(202, {"job_id": job_id, "status": "running"})
    if method == "POST" and path == "/client-error":
        return _accept_client_error(body)
    if method not in {"GET", "POST", "HEAD"}:
        return _plain(405, "Method not allowed")
    return _plain(404, "Not found")


def serve(state: AppState, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Listen until the process is stopped. Binds localhost by default."""

    handler = make_handler(state)
    try:
        server = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise SceneDataError(f"Could not listen on {host}:{port}: {exc}") from exc
    LOGGER.info("Lisbon scene page at http://%s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Stopping")
    finally:
        server.server_close()


def _read_note(path: Path) -> str:
    if not path.is_file():
        raise SceneDataError(f"Missing scene note: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SceneDataError(f"Could not read {path}: {exc}") from exc
    if not text.strip():
        raise SceneDataError(f"Scene note is empty: {path}")
    return text


def _load_quicklook(scene: SceneRecord) -> QuicklookImage | None:
    from .quicklook import QuicklookError, render_quicklook_png

    asset = scene.asset("qlk-cog")
    if asset is None or asset.local_path is None:
        LOGGER.error("Quicklook qlk-cog.tif is not on disk")
        return None
    try:
        return render_quicklook_png(asset.local_path)
    except QuicklookError as exc:
        raise SceneDataError(str(exc)) from exc


def _load_static(static_dir: Path) -> dict[str, tuple[str, bytes]]:
    wanted = {
        "scene.css": "text/css; charset=utf-8",
        "scene.js": "text/javascript; charset=utf-8",
    }
    loaded: dict[str, tuple[str, bytes]] = {}
    for name, content_type in wanted.items():
        path = static_dir / name
        if not path.is_file():
            raise SceneDataError(f"Missing static file: {path}")
        try:
            loaded[f"/static/{name}"] = (content_type, path.read_bytes())
        except OSError as exc:
            raise SceneDataError(f"Could not read {path}: {exc}") from exc
    return loaded


def _accept_client_error(body: bytes) -> HttpResponse:
    """Log a browser error. The body is capped so a page cannot fill the log."""

    if len(body) > _MAX_CLIENT_ERROR_BYTES:
        return _plain(413, "Client error report is too large")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _plain(400, "Client error report must be JSON")
    if not isinstance(payload, dict):
        return _plain(400, "Client error report must be a JSON object")
    message = _clip(payload.get("message"))
    source = _clip(payload.get("source"))
    LOGGER.error("browser error message=%s source=%s", message, source)
    return HttpResponse(204, "text/plain; charset=utf-8", b"")


def _scene_payload(
    state: AppState, job_manager: MeasurementJobManager
) -> dict[str, object]:
    scene = state.scene
    bbox = scene.bbox
    result = job_manager.disk_result().to_public()
    return {
        "scene_id": scene.scene_id,
        "collected_at": scene.collected_at,
        "start_at": scene.start_at,
        "end_at": scene.end_at,
        "platform": scene.platform,
        "mode": scene.mode,
        "band": scene.band,
        "polarizations": list(scene.polarizations),
        "orbit_state": scene.orbit_state,
        "incidence_angle": scene.incidence_angle,
        "bbox": [bbox.west, bbox.south, bbox.east, bbox.north],
        "preview_url": "/quicklook.png" if state.quicklook is not None else None,
        "measurement": result["measurement"],
        "briefing_html": result["briefing_html"],
        "overview_url": result["overview_url"],
    }


def _json(status: int, payload: dict[str, object]) -> HttpResponse:
    return HttpResponse(
        status,
        "application/json; charset=utf-8",
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )


def _ui_dist_dir() -> Path:
    return project_root() / "ui" / "dist"


def _dist_asset_response(path: str) -> HttpResponse | None:
    dist_dir = _ui_dist_dir()
    candidate = _safe_dist_path(dist_dir, path)
    if candidate is None or not candidate.is_file():
        return None
    cache = "no-store" if candidate.name == "index.html" else _IMMUTABLE_CACHE
    return _file_response(candidate, _content_type(candidate), cache)


def _safe_dist_path(dist_dir: Path, request_path: str) -> Path | None:
    relative = unquote(request_path).lstrip("/")
    if not relative or "\x00" in relative:
        return None
    if any(part in {"", ".", ".."} for part in relative.split("/")):
        return None
    root = dist_dir.resolve()
    candidate = (root / relative).resolve()
    try:
        if not candidate.is_relative_to(root):
            return None
    except ValueError:
        return None
    return candidate


def _file_response(
    path: Path, content_type: str, cache_control: str = "no-store"
) -> HttpResponse:
    try:
        body = path.read_bytes()
    except OSError:
        return _plain(404, "Not found")
    return HttpResponse(200, content_type, body, cache_control)


def _content_type(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(path.name)
    if guessed is None:
        return "application/octet-stream"
    if guessed.startswith("text/") or guessed in {
        "application/javascript",
        "application/json",
    }:
        return f"{guessed}; charset=utf-8"
    return guessed


def _plain(status: int, message: str) -> HttpResponse:
    body = f"{message}\n".encode()
    return HttpResponse(status, "text/plain; charset=utf-8", body)


def _clip(value: object) -> str:
    text = value if isinstance(value, str) else ""
    return " ".join(text.split())[:500]


def make_handler(
    state: AppState, job_manager: MeasurementJobManager | None = None
) -> type[BaseHTTPRequestHandler]:
    manager = job_manager or default_manager()

    class SceneHandler(BaseHTTPRequestHandler):
        """Stdlib request handler closed over the loaded scene."""

        def do_GET(self) -> None:
            self._reply(dispatch("GET", self.path, b"", state, manager))

        def do_HEAD(self) -> None:
            # Same status and headers as GET. The body stays on the server.
            response = dispatch("GET", self.path, b"", state, manager)
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.send_header("Cache-Control", response.cache_control)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()

        def do_POST(self) -> None:
            length = self._content_length(self.path)
            if length is None:
                self._reply(_plain(400, "Content-Length required"))
                return
            if length > _MAX_CLIENT_ERROR_BYTES:
                self._reply(_plain(413, "Client error report is too large"))
                return
            body = self.rfile.read(length)
            self._reply(dispatch("POST", self.path, body, state, manager))

        def _content_length(self, target: str) -> int | None:
            raw = self.headers.get("Content-Length")
            if raw is None:
                path = urlsplit(target).path
                return 0 if path == "/api/jobs/measure" else None
            try:
                length = int(raw)
            except ValueError:
                return None
            if length < 0:
                return None
            return length

        def _reply(self, response: HttpResponse) -> None:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.send_header("Cache-Control", response.cache_control)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(response.body)

        def log_message(self, fmt: str, *args: object) -> None:
            LOGGER.info("%s - %s", self.address_string(), fmt % args)

    return SceneHandler
