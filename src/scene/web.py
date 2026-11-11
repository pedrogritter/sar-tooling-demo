"""HTTP entry for the one-page scene viewer.

Routes are fixed. The process never serves the data directory by path.
Quicklooks, the local thumbnail, and the dwell video are explicit routes
for one scene id. Catalog thumbnails are proxied only after the server
has resolved an allowlisted ICEYE URL.
"""

from __future__ import annotations

import json
import logging
import math
import mimetypes
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlsplit

from .belt.catalog import analysis_dir, tools_for_scene
from .belt.run import step_sentences
from .catalog import (
    PREVIEW_KEYS,
    CatalogError,
    CatalogService,
    SearchQuery,
    default_catalog,
    is_large_asset,
    record_public,
)
from .demo import PlaceholderMissing, clear_placeholder, note_from_folder
from .downloads import (
    DownloadAlreadyRunningError,
    DownloadError,
    DownloadManager,
    default_downloads,
)
from .jobs import (
    JobAlreadyRunningError,
    MeasurementJobManager,
    OnStep,
    default_manager,
)
from .library import list_library
from .loader import SceneDataError, SceneRecord, load_scene
from .page import render_page
from .paths import (
    FETCH_COMMAND,
    LISBON_SCENE_ID,
    project_root,
    scene_dir,
    scene_note_path,
    static_dir,
    valid_scene_id,
)
from .report.facts import ReportFacts, report_facts
from .report.pdf import build_pdf
from .report.run import Phraser, run_amplitude, run_report
from .report.store import ReportStore
from .report.validate import validate_plan

if TYPE_CHECKING:
    from .quicklook import QuicklookImage

LOGGER = logging.getLogger("scene")
_MAX_CLIENT_ERROR_BYTES = 2048
_MAX_JSON_BYTES = 16384
_IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
_SCENE_ROUTE = re.compile(
    r"^/api/scenes/(?P<scene_id>[A-Za-z0-9_-]+)"
    r"(?:/(?P<leaf>quicklook\.png|thumbnail|video))?$"
)
_ITEM_ROUTE = re.compile(
    r"^/api/catalog/items/(?P<scene_id>[A-Za-z0-9_-]+)(?:/(?P<leaf>thumbnail))?$"
)
_ANALYSIS_ROUTE = re.compile(
    r"^/api/scenes/(?P<scene_id>[A-Za-z0-9_-]+)/analysis/(?P<tool>[a-z0-9-]+)"
    r"(?:/(?P<partner>[A-Za-z0-9_-]+))?/overview\.png$"
)
_TOOLS_ROUTE = re.compile(r"^/api/scenes/(?P<scene_id>[A-Za-z0-9_-]+)/tools$")
_REPORT_ROUTE = re.compile(
    r"^/api/scenes/(?P<scene_id>[A-Za-z0-9_-]+)/report"
    r"(?P<leaf>/plan|/run|/amplitude|\.pdf)?$"
)
_PARTNER_ID = re.compile(r"[A-Za-z0-9_-]+")
# The longest question a report accepts, in UTF-8 bytes.
_MAX_QUESTION_BYTES = 2048
NO_KEY_SENTENCE = "Set OPENAI_API_KEY to ask a question."
# The one tool that needs a second scene, so the report only waits for it.
_AMPLITUDE_TOOL = "amplitude-change"
_QUICKLOOK_CACHE: dict[str, tuple[int, bytes]] = {}


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


def build_state(
    stac_path: Path | None = None,
    note_path: Path | None = None,
) -> AppState:
    """Load the scene, the note, the quicklook PNG, and the static files.

    A missing STAC record or an empty note stops startup. A missing
    quicklook does not: the page explains that ``python -m scene.fetch``
    has not saved it yet.
    """

    scene = load_scene(stac_path)
    note_file = note_path or scene_note_path()
    note = _read_note(note_file)
    quicklook = _load_quicklook(scene)
    static_files = _load_static(static_dir())
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
    catalog: CatalogService | None = None,
    downloads: DownloadManager | None = None,
) -> HttpResponse:
    """Answer one request. Unknown paths and methods get a short error."""

    manager = job_manager or default_manager()
    path = urlsplit(target).path
    extra = _dispatch_workspace(method, target, body, manager, catalog, downloads)
    if extra is not None:
        return extra
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
            return _plain(404, f"Quicklook is not on disk. Run {FETCH_COMMAND}")
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
    LOGGER.info("Scene page at http://%s:%s", host, port)
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
    preview = "/quicklook.png" if state.quicklook is not None else None
    # /api/scene keeps the original contract: measurement comes from the
    # Lisbon intelligence directory even when the loaded record is a fixture.
    return _scene_document(state.scene, job_manager, preview, include_measurement=True)


def _scene_document(
    scene: SceneRecord,
    job_manager: MeasurementJobManager,
    preview_url: str | None,
    include_measurement: bool,
) -> dict[str, object]:
    bbox = scene.bbox
    result = (
        job_manager.disk_result().to_public()
        if include_measurement
        else {"measurement": None, "briefing_html": None, "overview_url": None}
    )
    graphic = scene.asset("graphic")
    video = scene.asset("vid-mp4")
    scene_id = scene.scene_id
    note = note_from_folder(scene_dir(scene_id))
    return {
        "scene_id": scene_id,
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
        "preview_url": preview_url,
        "thumbnail_url": (
            f"/api/scenes/{scene_id}/thumbnail"
            if graphic is not None and graphic.on_disk
            else None
        ),
        "video_url": (
            f"/api/scenes/{scene_id}/video"
            if video is not None and video.on_disk
            else None
        ),
        "assets_on_disk": [asset.key for asset in scene.assets if asset.on_disk],
        "is_test_scene": scene_id == LISBON_SCENE_ID,
        "placeholder": note is not None,
        "placeholder_note": note,
        "measurement": result["measurement"],
        "briefing_html": result["briefing_html"],
        "overview_url": result["overview_url"],
    }


def _dispatch_workspace(
    method: str,
    target: str,
    body: bytes,
    manager: MeasurementJobManager,
    catalog: CatalogService | None,
    downloads: DownloadManager | None,
) -> HttpResponse | None:
    """Catalog, library, scene, and download routes. None lets the old routes run."""

    path = urlsplit(target).path
    if path == "/api/library" and method == "GET":
        return _json(200, {"scenes": list_library()})
    if path == "/api/demo/clear" and method == "POST":
        return _clear_demo(body)
    if path == "/api/jobs/run" and method == "POST":
        return _start_analysis(body, manager)
    tools_match = _TOOLS_ROUTE.fullmatch(path)
    if tools_match is not None and method == "GET":
        return _scene_tools(tools_match.group("scene_id"))
    analysis_match = _ANALYSIS_ROUTE.fullmatch(path)
    if analysis_match is not None and method == "GET":
        return _analysis_png(
            analysis_match.group("scene_id"),
            analysis_match.group("tool"),
            analysis_match.group("partner"),
        )
    if path == "/api/downloads/current" and method == "GET":
        return _json(200, _downloads(downloads).current())
    if path == "/api/downloads" and method == "POST":
        return _start_download(body, _downloads(downloads))
    if path == "/api/catalog/search" and method == "GET":
        return _catalog_search(target, _catalog(catalog))
    if path == "/api/catalog/refresh" and method == "POST":
        return _catalog_refresh(body, _catalog(catalog))
    item = _ITEM_ROUTE.fullmatch(path)
    if item is not None and method == "GET":
        return _catalog_item(
            item.group("scene_id"),
            item.group("leaf"),
            _catalog(catalog),
        )
    report_match = _REPORT_ROUTE.fullmatch(path)
    if report_match is not None:
        reply = _report_route(
            method,
            report_match.group("scene_id"),
            report_match.group("leaf"),
            body,
            manager,
        )
        if reply is not None:
            return reply
    scene_match = _SCENE_ROUTE.fullmatch(path)
    if scene_match is not None and method == "GET":
        return _scene_route(
            scene_match.group("scene_id"), scene_match.group("leaf"), manager
        )
    return None


class _BeltOnlyPhraser:
    """Used when no key is set: every phrase fails, so the belt's text is kept."""

    def phrase(
        self, question: str, facts: ReportFacts, measurement: Mapping[str, object]
    ) -> str:
        raise RuntimeError(NO_KEY_SENTENCE)


def _report_phraser() -> Phraser:
    """The model chains when a key is set, else the belt-text fallback.

    The chains module is imported here, not at the top, so serving the page,
    the stored report, and the PDF never load a chat model library.
    """

    from .report.chains import chains_or_none

    chains = chains_or_none()
    return chains if chains is not None else _BeltOnlyPhraser()


def _report_route(
    method: str,
    scene_id: str,
    leaf: str | None,
    body: bytes,
    manager: MeasurementJobManager,
) -> HttpResponse | None:
    """The report routes for one scene. None when method and leaf do not match."""

    if method == "GET" and leaf is None:
        return _guard_scene(scene_id, _get_report)
    if method == "GET" and leaf == ".pdf":
        return _guard_scene(scene_id, _report_pdf)
    if method != "POST":
        return None
    if leaf == "/plan":
        return _guard_scene(scene_id, lambda sid: _plan_report(sid, body))
    if leaf == "/run":
        return _guard_scene(scene_id, lambda sid: _run_report(sid, body, manager))
    if leaf == "/amplitude":
        return _guard_scene(scene_id, lambda sid: _run_amplitude(sid, body, manager))
    return None


def _guard_scene(scene_id: str, handler: Callable[[str], HttpResponse]) -> HttpResponse:
    """Run ``handler`` only for a scene that is on disk."""

    if not _scene_on_disk(scene_id):
        return _plain(404, "Scene is not on disk")
    return handler(scene_id)


def _get_report(scene_id: str) -> HttpResponse:
    """The stored report, partial while a job runs. Empty when none was saved."""

    try:
        report = ReportStore(scene_id).load()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        LOGGER.error("report for %s could not be read: %s", scene_id, exc)
        return _plain(500, "The saved report could not be read")
    if report is None:
        return _json(200, {"scene_id": scene_id, "question": "", "sections": []})
    return _json(200, asdict(report))


def _report_pdf(scene_id: str) -> HttpResponse:
    """The stored report as a PDF. It never builds a model."""

    try:
        report = ReportStore(scene_id).load()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        LOGGER.error("report for %s could not be read: %s", scene_id, exc)
        return _plain(500, "The saved report could not be read")
    if report is None:
        return _plain(404, "There is no report for this scene yet")
    try:
        document = build_pdf(report)
    except Exception as exc:  # noqa: BLE001 - one bad section must not kill the server.
        LOGGER.exception("report PDF for %s failed", scene_id)
        return _plain(500, f"The PDF could not be built: {exc}")
    return HttpResponse(200, "application/pdf", document)


def _json_body(body: bytes) -> dict[str, object] | HttpResponse:
    """The request body as a JSON object, or the 400 that says what is wrong."""

    if not body:
        return _plain(400, "Request body must be a JSON object")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _plain(400, "Request body must be JSON")
    if not isinstance(payload, dict):
        return _plain(400, "Request body must be a JSON object")
    return payload


def _question(payload: dict[str, object]) -> str | HttpResponse:
    """The trimmed question. Empty, missing, or over 2 KiB is a 400."""

    raw = payload.get("question")
    if not isinstance(raw, str) or not raw.strip():
        return _plain(400, "question must be a non-empty string")
    question = raw.strip()
    if len(question.encode("utf-8")) > _MAX_QUESTION_BYTES:
        return _plain(400, f"question must be at most {_MAX_QUESTION_BYTES} bytes")
    return question


def _read_facts(scene_id: str) -> ReportFacts | HttpResponse:
    try:
        return report_facts(scene_id)
    except (SceneDataError, OSError, ValueError) as exc:
        return _plain(404, str(exc))


def _plan_report(scene_id: str, body: bytes) -> HttpResponse:
    """Ask the model which tools answer the question. Nothing is measured."""

    payload = _json_body(body)
    if isinstance(payload, HttpResponse):
        return payload
    question = _question(payload)
    if isinstance(question, HttpResponse):
        return question
    facts = _read_facts(scene_id)
    if isinstance(facts, HttpResponse):
        return facts
    from .report.chains import chains_or_none

    chains = chains_or_none()
    if chains is None:
        return _plain(409, NO_KEY_SENTENCE)
    try:
        raw = chains.plan(question, facts)
    except Exception as exc:  # noqa: BLE001 - a model failure is a gateway error.
        LOGGER.exception("report plan for %s failed", scene_id)
        return _plain(502, f"The model could not plan the report: {_clip(str(exc))}")
    return _json(200, asdict(validate_plan(facts, raw)))


def _run_report(
    scene_id: str, body: bytes, manager: MeasurementJobManager
) -> HttpResponse:
    """Check the posted tool ids against fresh facts, then start the run."""

    payload = _json_body(body)
    if isinstance(payload, HttpResponse):
        return payload
    question = _question(payload)
    if isinstance(question, HttpResponse):
        return question
    tool_ids = payload.get("tool_ids")
    if not isinstance(tool_ids, list) or not all(
        isinstance(item, str) for item in tool_ids
    ):
        return _plain(400, "tool_ids must be a list of strings")
    facts = _read_facts(scene_id)
    if isinstance(facts, HttpResponse):
        return facts
    plan = validate_plan(
        facts, {"tools": tool_ids, "catalogue_only": [], "partner_id": None}
    )
    allowed = {*plan.selected, *plan.waiting}
    unknown = [item for item in tool_ids if item not in allowed]
    if unknown or not allowed:
        return _plain(
            400, f"Tools that cannot run for this scene: {unknown or 'none chosen'}"
        )

    def runner(on_step: OnStep) -> None:
        run_report(scene_id, question, plan, _report_phraser(), on_step)

    try:
        job_id = manager.start_report(runner)
    except JobAlreadyRunningError:
        return _json(409, {"status": "running"})
    return _json(202, {"job_id": job_id, "status": "running"})


def _run_amplitude(
    scene_id: str, body: bytes, manager: MeasurementJobManager
) -> HttpResponse:
    """Run amplitude change against one eligible partner scene."""

    payload = _json_body(body)
    if isinstance(payload, HttpResponse):
        return payload
    partner_id = payload.get("partner_id")
    if not isinstance(partner_id, str) or not _PARTNER_ID.fullmatch(partner_id):
        return _plain(400, "partner_id must be one scene id")
    try:
        views = {item.id: item for item in tools_for_scene(scene_id)}
    except (SceneDataError, OSError, ValueError) as exc:
        return _plain(404, str(exc))
    amplitude = views.get(_AMPLITUDE_TOOL)
    if amplitude is None or amplitude.locked or partner_id not in amplitude.partners:
        return _plain(400, "partner_id is not a scene amplitude change can compare")

    def runner(on_step: OnStep) -> None:
        run_amplitude(scene_id, partner_id, _report_phraser(), on_step)

    try:
        job_id = manager.start_report(runner)
    except JobAlreadyRunningError:
        return _json(409, {"status": "running"})
    return _json(202, {"job_id": job_id, "status": "running"})


def _clear_demo(body: bytes) -> HttpResponse:
    """Remove placeholder pictures. A real scene folder is not deleted."""

    if body:
        return _plain(400, "Clear demo request body must be empty")
    try:
        note = clear_placeholder()
    except PlaceholderMissing:
        return _plain(404, "No demo placeholder is on disk")
    return _json(200, {"cleared": True, "note": note})


def _scene_tools(scene_id: str) -> HttpResponse:
    if (
        not valid_scene_id(scene_id)
        or not (scene_dir(scene_id) / "stac.json").is_file()
    ):
        return _plain(404, "Scene is not on disk")
    try:
        tools = [item.to_public() for item in tools_for_scene(scene_id)]
    except SceneDataError as exc:
        return _plain(404, str(exc))
    return _json(200, {"tools": tools})


def _analysis_png(scene_id: str, tool_id: str, partner_id: str | None) -> HttpResponse:
    if not valid_scene_id(scene_id):
        return _plain(404, "Not found")
    if partner_id is not None and not valid_scene_id(partner_id):
        return _plain(404, "Not found")
    path = analysis_dir(scene_id, tool_id, partner_id) / "overview.png"
    if not path.is_file() or not _inside_scene(scene_id, path):
        return _plain(404, "Overview is not on disk")
    return _file_response(path, "image/png")


def _start_analysis(body: bytes, manager: MeasurementJobManager) -> HttpResponse:
    if not body:
        return _plain(400, "Analysis body must name a scene_id and a tool_id")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _plain(400, "Analysis body must be JSON")
    if not isinstance(payload, dict):
        return _plain(400, "Analysis body must be a JSON object")
    scene_id = payload.get("scene_id")
    tool_id = payload.get("tool_id")
    partner_id = payload.get("partner_id")
    if not isinstance(scene_id, str) or not valid_scene_id(scene_id):
        return _plain(400, "scene_id must be a scene id")
    if not isinstance(tool_id, str) or not tool_id:
        return _plain(400, "tool_id must be a string")
    if partner_id is not None and (
        not isinstance(partner_id, str) or not valid_scene_id(partner_id)
    ):
        return _plain(400, "partner_id must be a scene id")
    try:
        views = {item.id: item for item in tools_for_scene(scene_id)}
    except SceneDataError as exc:
        return _plain(404, str(exc))
    except KeyError:
        return _plain(400, "Unknown tool")
    view = views.get(tool_id)
    if view is None:
        return _plain(400, "Unknown tool")
    if view.locked:
        return _plain(400, view.reason)
    chosen = partner_id if isinstance(partner_id, str) else None
    if view.needs_partner and (chosen is None or chosen not in view.partners):
        return _plain(400, "Choose a second scene with the same look.")
    folder = analysis_dir(scene_id, tool_id, chosen if view.needs_partner else None)
    if view.needs_partner and chosen is not None:
        overview = f"/api/scenes/{scene_id}/analysis/{tool_id}/{chosen}/overview.png"
    else:
        overview = f"/api/scenes/{scene_id}/analysis/{tool_id}/overview.png"
        chosen = None
    try:
        job_id = manager.start_analysis(
            scene_id,
            tool_id,
            chosen,
            folder,
            overview,
            len(step_sentences(tool_id)),
        )
    except JobAlreadyRunningError:
        return _json(409, {"status": "running"})
    except KeyError:
        return _plain(400, "Unknown tool")
    return _json(202, {"job_id": job_id, "status": "running"})


def _catalog(catalog: CatalogService | None) -> CatalogService:
    return catalog if catalog is not None else default_catalog()


def _downloads(downloads: DownloadManager | None) -> DownloadManager:
    return downloads if downloads is not None else default_downloads()


def _catalog_search(target: str, catalog: CatalogService) -> HttpResponse:
    try:
        catalog.ensure_ready()
        query = _search_query(target)
    except CatalogError as exc:
        return _plain(502, str(exc))
    except ValueError as exc:
        return _plain(400, str(exc))
    result = catalog.search(query)
    catalog.prioritize([item.scene_id for item in result.items])
    catalog.kick()
    return _json(
        200,
        {
            "items": [
                record_public(item, _scene_on_disk(item.scene_id))
                for item in result.items
            ],
            "total": result.total,
            "offset": result.offset,
            "limit": result.limit,
            "indexed": result.indexed,
            "record_count": result.record_count,
            "indexing": result.indexing,
            "unread_for_bbox": result.unread_for_bbox,
            "satellites": list(result.satellites),
            "products": list(result.products),
        },
    )


def _catalog_refresh(body: bytes, catalog: CatalogService) -> HttpResponse:
    if body not in {b"", b"{}"}:
        return _plain(400, "Catalog refresh body must be empty")
    try:
        catalog.refresh()
    except CatalogError as exc:
        return _plain(502, str(exc))
    return _json(202, {"status": "refreshing"})


def _catalog_item(
    scene_id: str, leaf: str | None, catalog: CatalogService
) -> HttpResponse:
    try:
        catalog.ensure_ready()
        if leaf == "thumbnail":
            content_type, payload = catalog.thumbnail(scene_id)
            return HttpResponse(200, content_type, payload)
        record = catalog.enrich_item(scene_id)
        sizes = catalog.asset_sizes(record.assets)
    except KeyError:
        return _plain(404, "Catalog item not found")
    except CatalogError as exc:
        return _plain(502, str(exc))
    document = record_public(record, _scene_on_disk(scene_id))
    document["assets"] = [
        {
            "key": asset.key,
            "title": asset.title,
            "roles": list(asset.roles),
            "media_type": asset.media_type,
            "bytes": sizes.get(asset.key),
            "preview_default": asset.key in PREVIEW_KEYS,
            "large": is_large_asset(asset.key, asset.roles),
        }
        for asset in record.assets
    ]
    return _json(200, document)


def _scene_route(
    scene_id: str, leaf: str | None, manager: MeasurementJobManager
) -> HttpResponse:
    if not valid_scene_id(scene_id):
        return _plain(404, "Not found")
    if leaf == "quicklook.png":
        return _scene_quicklook(scene_id)
    if leaf == "thumbnail":
        return _scene_file(scene_id, "graphic")
    if leaf == "video":
        return _scene_file(scene_id, "vid-mp4")
    return _scene_json(scene_id, manager)


def _scene_json(scene_id: str, manager: MeasurementJobManager) -> HttpResponse:
    scene = _read_local_scene(scene_id)
    if isinstance(scene, HttpResponse):
        return scene
    quicklook = scene.asset("qlk-cog")
    graphic = scene.asset("graphic")
    preview = None
    if (quicklook is not None and quicklook.on_disk) or (
        graphic is not None and graphic.on_disk
    ):
        preview = f"/api/scenes/{scene_id}/quicklook.png"
    return _json(
        200,
        _scene_document(
            scene,
            manager,
            preview,
            include_measurement=scene.scene_id == LISBON_SCENE_ID,
        ),
    )


def _scene_quicklook(scene_id: str) -> HttpResponse:
    scene = _read_local_scene(scene_id)
    if isinstance(scene, HttpResponse):
        return scene
    quicklook = scene.asset("qlk-cog")
    if quicklook is not None and quicklook.local_path is not None:
        stamp = quicklook.local_path.stat().st_mtime_ns
        cached = _QUICKLOOK_CACHE.get(scene_id)
        if cached is not None and cached[0] == stamp:
            return HttpResponse(200, "image/png", cached[1])
        from .quicklook import QuicklookError, render_quicklook_png

        try:
            image = render_quicklook_png(quicklook.local_path)
        except QuicklookError as exc:
            return _plain(404, str(exc))
        _QUICKLOOK_CACHE[scene_id] = (stamp, image.png)
        return HttpResponse(200, "image/png", image.png)
    return _scene_file(scene_id, "graphic")


def _scene_file(scene_id: str, key: str) -> HttpResponse:
    scene = _read_local_scene(scene_id)
    if isinstance(scene, HttpResponse):
        return scene
    asset = scene.asset(key)
    if (
        asset is None
        or asset.local_path is None
        or not _inside_scene(scene_id, asset.local_path)
    ):
        return _plain(404, "Not found")
    if key == "vid-mp4":
        return _file_response(asset.local_path, "video/mp4")
    return _file_response(asset.local_path, "image/png")


def _read_local_scene(scene_id: str) -> SceneRecord | HttpResponse:
    if not valid_scene_id(scene_id):
        return _plain(404, "Not found")
    path = scene_dir(scene_id) / "stac.json"
    if not path.is_file():
        return _plain(404, "Scene is not on disk")
    try:
        return load_scene(path)
    except SceneDataError as exc:
        return _plain(404, str(exc))


def _inside_scene(scene_id: str, path: Path) -> bool:
    root = scene_dir(scene_id).resolve()
    try:
        return path.resolve().is_relative_to(root)
    except (OSError, ValueError):
        return False


def _scene_on_disk(scene_id: str) -> bool:
    if not valid_scene_id(scene_id):
        return False
    return (scene_dir(scene_id) / "stac.json").is_file()


def _search_query(target: str) -> SearchQuery:
    params = parse_qs(urlsplit(target).query, keep_blank_values=False)

    def one(name: str) -> str | None:
        values = params.get(name)
        if not values:
            return None
        text = values[0].strip()
        return text or None

    limit = _query_int(one("limit"), 24)
    offset = _query_int(one("offset"), 0)
    return SearchQuery(
        q=one("q") or "",
        start=one("start"),
        end=one("end"),
        satellite=one("satellite"),
        product=one("product"),
        bbox=_query_bbox(one("bbox")),
        limit=limit,
        offset=offset,
    )


def _query_bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    if raw is None:
        return None
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be west,south,east,north")
    try:
        west, south, east, north = (float(part) for part in parts)
    except ValueError as exc:
        raise ValueError("bbox must be west,south,east,north") from exc
    if not all(math.isfinite(value) for value in (west, south, east, north)):
        raise ValueError("bbox must be west,south,east,north")
    if west >= east or south >= north:
        raise ValueError("bbox must be west,south,east,north")
    return west, south, east, north


def _query_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError("limit and offset must be integers") from exc


def _start_download(body: bytes, downloads: DownloadManager) -> HttpResponse:
    if not body:
        return _plain(400, "Download body must name an item_id")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _plain(400, "Download body must be JSON")
    if not isinstance(payload, dict):
        return _plain(400, "Download body must be a JSON object")
    item_id = payload.get("item_id")
    assets = payload.get("assets")
    if not isinstance(item_id, str) or not item_id:
        return _plain(400, "item_id must be a string")
    chosen: list[str] | None
    if assets is None:
        chosen = None
    elif isinstance(assets, list) and all(isinstance(key, str) for key in assets):
        chosen = list(assets)
    else:
        return _plain(400, "assets must be a list of strings")
    try:
        job_id = downloads.start(item_id, chosen)
    except DownloadAlreadyRunningError:
        return _json(409, {"status": "running"})
    except DownloadError as exc:
        return _plain(400, str(exc))
    return _json(202, {"job_id": job_id, "status": "running"})


def _json(status: int, payload: dict[str, object]) -> HttpResponse:
    return HttpResponse(
        status,
        "application/json; charset=utf-8",
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )


def _ui_dist_dir() -> Path:
    return project_root() / "frontend" / "dist"


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


def _body_limit(target: str) -> int:
    path = urlsplit(target).path
    if path == "/client-error":
        return _MAX_CLIENT_ERROR_BYTES
    return _MAX_JSON_BYTES


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
            if length > _body_limit(self.path):
                self._reply(_plain(413, "Request body is too large"))
                return
            body = self.rfile.read(length)
            self._reply(dispatch("POST", self.path, body, state, manager))

        def _content_length(self, target: str) -> int | None:
            raw = self.headers.get("Content-Length")
            if raw is None:
                path = urlsplit(target).path
                if path in {
                    "/api/jobs/measure",
                    "/api/catalog/refresh",
                    "/api/demo/clear",
                }:
                    return 0
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
            self.send_header("Cache-Control", response.cache_control)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(response.body)

        def log_message(self, fmt: str, *args: object) -> None:
            LOGGER.info("%s - %s", self.address_string(), fmt % args)

    return SceneHandler
