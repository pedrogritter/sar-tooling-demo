# Verifier notes — python-job-api

Verification of target `python-job-api` on branch `orch/scene-web-view/python-job-api`
(HEAD 5600370 "Add scene measurement job API").

## Commands run

```
python3 -m unittest tests.test_jobs -v     # 10 passed
# raster-open audit hook wrapping builtins.open while running tests.test_jobs
#   -> RASTER/TIF OPENS DETECTED: []   (no .tif / cog file opened)
python3 -m ruff check .                     # 1 error: I001 in tests/test_jobs.py
python3 -m mypy                             # 7 errors, all in tests/test_jobs.py
python3 -m ruff check <prod files>          # clean
python3 -m mypy app.py lisbon_scene/...     # clean (in-scope prod code)
```

## Behavioral acceptance criteria — all met

- run_measurement(on_step) exists; main() calls it; `wait_for` download poll no longer on job path.
- nine exact sentences emitted in order (test asserts == enumerate(EXPECTED_STEPS, 1)).
- One thread + one lock in MeasurementJobManager; POST /api/jobs/measure -> 202 / 409.
- GET /api/scene and GET /api/jobs/current match contract shapes.
- Missing required raster fails with "Missing data/grd-cog.tif. Run python3 scene.py --all."; no download.
- GET / serves ui/dist/index.html when present (no-store), else render_page fallback; hashed /assets/* cached immutable, path traversal blocked.
- GET /overview.png from intelligence/overview.png only; /client-error and /quicklook.png retained.
- tests/test_jobs.py passes (10) with fake runner, opens no raster.

## Gate findings (not in the 8 acceptance bullets, but in scoped-task constraints)

Production code (`lisbon_scene/jobs.py`, `lisbon_scene/web.py`, `app.py`, and `analyze.py`
for ruff) passes both ruff and the config-scoped mypy. The *test file* does not:

- ruff `I001` import sort: `from typing import Any, TYPE_CHECKING, cast` should be
  `TYPE_CHECKING, Any, cast` (tests/test_jobs.py:16).
- mypy strict (7): `importlib.util` attribute errors (needs `import importlib.util`) and
  unused `type: ignore` comments (tests/test_jobs.py:28,30,34,40,42,44,49).

analyze.py is intentionally excluded from mypy by pyproject (`files = [...]`), so its
mypy errors are out of scope.
