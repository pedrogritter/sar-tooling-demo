<!-- orchestrate handoff
task: python-job-api
branch: orch/scene-web-view/python-job-api
agentId: bc-48d866fa-a205-47df-84ce-88cd2e3a8165
runId: run-68b74776-3589-4271-bc8f-93d1d96a6b04
resultStatus: finished
finishedAt: 2026-11-09T17:01:42.577Z
-->

## Status
success

## Branch
`orch/scene-web-view/python-job-api`

## What I did
- `analyze.py`: added `run_measurement(on_step)` with the nine exact step sentences, fail-fast local raster checks, and preserved CLI execution through `main()`.
- `lisbon_scene/jobs.py`: added a single-worker measurement job manager with injectable runner, status snapshots, result loading, and 409 protection.
- `lisbon_scene/web.py`: added `/api/scene`, `/api/jobs/measure`, `/api/jobs/current`, `/overview.png`, Vite dist/index serving, dist asset cache behavior, and empty POST handling.
- `tests/test_jobs.py`: added fake-runner tests covering idle/running/done/failed/409, API shapes, fallback vs dist index, overview serving, missing raster failure, and missing Content-Length POST.

## Measurements
- `tests.test_jobs passing tests: 0 → 10`
- `job step_count: absent → 9`

## Verification
unit-test-verified

## Notes, concerns, deviations, findings, thoughts, feedback
- Verified with `python3 -m unittest tests.test_jobs` and `python3 -m compileall -q analyze.py lisbon_scene/web.py lisbon_scene/jobs.py tests/test_jobs.py`.
- `python3 -m ruff ...` and `python3 -m mypy ...` could not run because `ruff` and `mypy` are not installed in this environment.
- No rasters were opened by the job tests, no downloads were started, and no TypeScript/UI/Docker/RAG/LangChain/Ollama/Kubernetes files were touched.
- Pushed the branch only; no PR opened per scoped worker instruction.

## Suggested follow-ups
- Run repo lint/type checks in an environment with `ruff` and `mypy` installed.
- Have the join worker verify compatibility with the TypeScript page once chunks 2 and 3 land.