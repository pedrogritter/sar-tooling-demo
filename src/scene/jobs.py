"""Background measurement job state for the local scene server."""

from __future__ import annotations

import importlib
import json
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .markdown import render_markdown
from .paths import intelligence_dir

JobStatus = Literal["idle", "running", "done", "failed"]
OnStep = Callable[[int, str], None]
MeasurementRunner = Callable[[OnStep], None]
STEP_COUNT = 9


class JobAlreadyRunningError(Exception):
    """Raised when a new measurement is requested while one is active."""


@dataclass(frozen=True)
class JobResult:
    measurement: object | None
    briefing_html: str | None
    overview_url: str | None

    def to_public(self) -> dict[str, object]:
        return {
            "measurement": self.measurement,
            "briefing_html": self.briefing_html,
            "overview_url": self.overview_url,
        }


@dataclass(frozen=True)
class JobSnapshot:
    status: JobStatus
    job_id: str | None
    step_index: int
    step_count: int
    sentence: str
    error: str | None
    result: JobResult | None

    def to_public(self) -> dict[str, object]:
        return {
            "status": self.status,
            "step_index": self.step_index,
            "step_count": self.step_count,
            "sentence": self.sentence,
            "error": self.error,
            "result": None if self.result is None else self.result.to_public(),
        }


class MeasurementJobManager:
    """Own the single measurement worker thread and its visible status."""

    def __init__(
        self,
        runner: MeasurementRunner | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self.output_dir = output_dir or default_output_dir()
        self._runner = runner or _default_runner
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._job_id: str | None = None
        self._status: JobStatus = "idle"
        self._step_index = 0
        self._sentence = ""
        self._error: str | None = None
        self._result: JobResult | None = None
        self._result_dir: Path | None = None
        self._overview_url = "/overview.png"
        self._step_count = STEP_COUNT
        self._active_runner: MeasurementRunner = self._runner

    def start(self) -> str:
        return self._begin(self._runner, self.output_dir, "/overview.png", STEP_COUNT)

    def start_analysis(
        self,
        scene_id: str,
        tool_id: str,
        partner_id: str | None,
        output_dir: Path,
        overview_url: str,
        step_count: int,
    ) -> str:
        """Run one belt tool. The Lisbon measurement keeps ``start``."""

        def runner(on_step: OnStep) -> None:
            module = importlib.import_module("scene.belt.run")
            run_tool = getattr(module, "run_tool")
            if not callable(run_tool):
                raise RuntimeError("scene.belt.run.run_tool is not callable")
            run_tool(scene_id, tool_id, on_step, partner_id)

        return self._begin(runner, output_dir, overview_url, step_count)

    def _begin(
        self,
        runner: MeasurementRunner,
        result_dir: Path,
        overview_url: str,
        step_count: int,
    ) -> str:
        with self._lock:
            if self._status == "running":
                raise JobAlreadyRunningError("A measurement job is already running")
            job_id = uuid.uuid4().hex
            self._job_id = job_id
            self._status = "running"
            self._step_index = 0
            self._sentence = ""
            self._error = None
            self._result = None
            self._result_dir = result_dir
            self._overview_url = overview_url
            self._step_count = step_count
            self._active_runner = runner
            thread = threading.Thread(
                target=self._run,
                args=(job_id,),
                daemon=True,
                name=f"measurement-{job_id[:8]}",
            )
            self._thread = thread
        thread.start()
        return job_id

    def current(self) -> JobSnapshot:
        with self._lock:
            return JobSnapshot(
                status=self._status,
                job_id=self._job_id,
                step_index=self._step_index,
                step_count=self._step_count,
                sentence=self._sentence,
                error=self._error,
                result=self._result,
            )

    def disk_result(self) -> JobResult:
        return read_job_result(self.output_dir)

    def _run(self, job_id: str) -> None:
        def on_step(index: int, sentence: str) -> None:
            with self._lock:
                if self._job_id != job_id or self._status != "running":
                    return
                self._step_index = index
                self._sentence = sentence

        try:
            self._active_runner(on_step)
        except Exception as exc:  # noqa: BLE001 - all failures become job status.
            reason = _short_reason(exc)
            with self._lock:
                if self._job_id != job_id:
                    return
                self._status = "failed"
                self._sentence = reason
                self._error = reason
                self._result = None
            return
        result = read_job_result(
            self._result_dir or self.output_dir, self._overview_url
        )
        with self._lock:
            if self._job_id != job_id:
                return
            self._status = "done"
            self._error = None
            self._result = result


def default_output_dir() -> Path:
    return intelligence_dir()


def read_job_result(
    output_dir: Path | None = None, overview_url: str = "/overview.png"
) -> JobResult:
    directory = output_dir or default_output_dir()
    ready = (directory / "overview.png").is_file()
    return JobResult(
        measurement=_read_measurement(directory / "measurements.json"),
        briefing_html=_read_briefing(directory / "briefing.md"),
        overview_url=overview_url if ready else None,
    )


_DEFAULT_MANAGER: MeasurementJobManager | None = None


def default_manager() -> MeasurementJobManager:
    global _DEFAULT_MANAGER
    if _DEFAULT_MANAGER is None:
        _DEFAULT_MANAGER = MeasurementJobManager()
    return _DEFAULT_MANAGER


def _default_runner(on_step: OnStep) -> None:
    module = importlib.import_module("scene.analyze")
    runner = getattr(module, "run_measurement")
    if not callable(runner):
        raise RuntimeError("scene.analyze.run_measurement is not callable")
    runner(on_step)


def _read_measurement(path: Path) -> object | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_briefing(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        markdown = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not markdown.strip():
        return None
    return render_markdown(markdown)


def _short_reason(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return " ".join(text.split())[:500]
