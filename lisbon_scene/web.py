"""HTTP entry for the one-page scene viewer.

Routes are fixed. The process never serves the data directory, so a
request cannot read the dwell video or any other file by path.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .loader import SceneDataError, SceneRecord, load_scene
from .page import render_page
from .quicklook import QuicklookError, QuicklookImage, render_quicklook_png

LOGGER = logging.getLogger("lisbon_scene")
_MAX_CLIENT_ERROR_BYTES = 2048
_NOTE_NAME = "scene_note.md"


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


def dispatch(method: str, target: str, body: bytes, state: AppState) -> HttpResponse:
    """Answer one request. Unknown paths and methods get a short error."""

    path = urlsplit(target).path
    if method == "GET" and path == "/":
        quicklook = state.quicklook
        page = render_page(
            state.scene,
            state.note_markdown,
            None if quicklook is None else quicklook.width,
            None if quicklook is None else quicklook.height,
        )
        return HttpResponse(200, "text/html; charset=utf-8", page.encode("utf-8"))
    if method == "GET" and path == "/quicklook.png":
        if state.quicklook is None:
            return _plain(404, "Quicklook is not on disk. Run python3 scene.py")
        return HttpResponse(200, "image/png", state.quicklook.png)
    if method == "GET" and path in state.static_files:
        content_type, payload = state.static_files[path]
        return HttpResponse(200, content_type, payload)
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


def _plain(status: int, message: str) -> HttpResponse:
    body = f"{message}\n".encode()
    return HttpResponse(status, "text/plain; charset=utf-8", body)


def _clip(value: object) -> str:
    text = value if isinstance(value, str) else ""
    return " ".join(text.split())[:500]


def make_handler(state: AppState) -> type[BaseHTTPRequestHandler]:
    class SceneHandler(BaseHTTPRequestHandler):
        """Stdlib request handler closed over the loaded scene."""

        def do_GET(self) -> None:
            self._reply(dispatch("GET", self.path, b"", state))

        def do_HEAD(self) -> None:
            # Same status and headers as GET. The body stays on the server.
            response = dispatch("GET", self.path, b"", state)
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()

        def do_POST(self) -> None:
            length = self._content_length()
            if length is None:
                self._reply(_plain(400, "Content-Length required"))
                return
            if length > _MAX_CLIENT_ERROR_BYTES:
                self._reply(_plain(413, "Client error report is too large"))
                return
            body = self.rfile.read(length)
            self._reply(dispatch("POST", self.path, body, state))

        def _content_length(self) -> int | None:
            raw = self.headers.get("Content-Length")
            if raw is None:
                return None
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
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(response.body)

        def log_message(self, fmt: str, *args: object) -> None:
            LOGGER.info("%s - %s", self.address_string(), fmt % args)

    return SceneHandler
