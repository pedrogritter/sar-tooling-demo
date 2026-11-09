<!-- orchestrate handoff
task: verify-python-job-api
branch: `orch/scene-web-view/python-job-api` (verifier note committed as `98b089b`, pushed)
agentId: bc-ffd5ccf8-6148-478f-885a-e841838d258c
runId: run-cb52ac59-1888-41d0-a0fb-ffe11b6411da
resultStatus: finished
finishedAt: 2026-11-09T17:05:42.949Z
-->

## Verification
unit-test-verified

## Target
`python-job-api` on branch `orch/scene-web-view/python-job-api`

## Branch
`orch/scene-web-view/python-job-api` (verifier note committed as `98b089b`, pushed)

## Execution
- `python3 -m unittest tests.test_jobs -v` → **10 passed, 0 failed** (`Ran 10 tests ... OK`), covering idle/running/done/failed, the 409 conflict, the nine ordered step sentences, missing-raster fail-fast, `/api/scene` and `/api/jobs/current` shapes, `/` fallback-vs-dist-index, `/overview.png`, dist-asset caching + path traversal, and empty POST without Content-Length.
- Re-ran `tests.test_jobs` wrapping `builtins.open` with an audit hook → `RASTER/TIF OPENS DETECTED: []` — no `.tif`/cog file is opened during the tests.
- `grep wait_for( analyze.py` → `wait_for` is only defined, never called from `run_measurement`/`main` (the 6-hour download poll is off the job path).
- `python3 -m ruff check .` → 1 error (`I001` in `tests/test_jobs.py`); prod files (`analyze.py`, `jobs.py`, `web.py`, `app.py`) clean.
- `python3 -m mypy` (project config, scopes `app.py`/`lisbon_scene`/`tests`) → 7 errors, all in `tests/test_jobs.py`; in-scope prod code clean.

## Findings
Per acceptance criterion:
- [x] `run_measurement(on_step)` exists; `python3 analyze.py` still runs the same work: `main()` calls `run_measurement()`; test drives the full body (patched heavy fns) and confirms `briefing.md` is written. (met)
- [x] `on_step` called with the nine exact sentences in order: test asserts `steps == list(enumerate(EXPECTED_STEPS, 1))`. (met)
- [x] One background thread + one lock; POST `/api/jobs/measure` → 202 or 409: `MeasurementJobManager` uses one `threading.Lock` and one worker thread; lifecycle test shows 202 then 409. (met)
- [x] GET `/api/scene` and `/api/jobs/current` match the contract: shape tests pass (bbox `[w,s,e,n]`, `preview_url`, `measurement`, `briefing_html`, `overview_url`; current returns status/step_index/step_count=9/sentence/error/result). (met)
- [x] Missing required raster fails naming the file and `python3 scene.py --all`; no download: error = `Missing data/grd-cog.tif. Run python3 scene.py --all.`, raised by a pure `is_file()` check. (met)
- [x] GET `/` serves `ui/dist/index.html` when present (no-store) else today's page; hashed dist assets cached, index not: test confirms fallback, index serving, `no-store` on index, and `public, max-age=31536000, immutable` on `/assets/*`. (met)
- [x] GET `/overview.png` from `intelligence/overview.png` only; `/client-error` + `/quicklook.png` remain: 404 when absent, 200 from intelligence dir; both other routes still dispatched. (met)
- [x] `tests/test_jobs.py` passes with a fake runner and opens no raster: 10/10 pass, audit hook confirms zero raster opens. (met)

Other findings (severity-ordered):
- (med) **`tests/test_jobs.py` fails the project's own lint/type gates.** `ruff check .` → `I001` (`from typing import Any, TYPE_CHECKING, cast` should be `TYPE_CHECKING, Any, cast`, line 16). `mypy` (config-scoped, strict) → 7 errors: `importlib.util` attribute errors (needs `import importlib.util`) at lines 28/30/34/44 and unused `type: ignore` at 40/42/49. A CI step running `ruff check .`/`mypy` would fail even though every behavioral criterion passes. Production code (`jobs.py`, `web.py`, `app.py`) is clean, so the scoped "jobs.py and web.py must typecheck" constraint is satisfied — the gap is only in the test file.
- (low) `analyze.py` shows 78 mypy errors if forced onto the CLI, but pyproject's `files` list excludes `analyze.py` from mypy by design (per discovered facts), so this is out of scope and not a regression.

## Notes & suggestions
- Verdict is `unit-test-verified` rather than `live-ui-verified` because this chunk is a Python backend with no UI; the test suite exercises the real `dispatch`, `make_handler`, `MeasurementJobManager`, and `run_measurement` code paths end-to-end.
- `ruff`/`mypy` were not preinstalled; I installed them via `pip` (ruff 0.17.4, mypy 2.4.1 from the environment index) to run the gates the upstream worker couldn't.
- Suggested follow-up for the join/integration worker: fix the four `importlib.util` references (add `import importlib.util`), drop the three unused `type: ignore` comments, and reorder the `typing` import in `tests/test_jobs.py` so the full `ruff check .` + `mypy` gate is green. Behavior needs no change.
- I did not modify any target source file; the only commit on the branch is the verifier notes (`VERIFIER_NOTES_python-job-api.md`).