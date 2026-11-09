<!-- orchestrate handoff
task: join-scene-web
branch: orch/scene-web-view/join-scene-web
agentId: bc-e4184a2d-d304-4eae-b778-e183b704f066
runId: run-3334524b-cfb0-41bb-8d7b-f18e2efed865
resultStatus: finished
finishedAt: 2026-11-09T17:46:56.136Z
-->

## Status
success

## Branch
`orch/scene-web-view/join-scene-web`

## What I did
- Merged `python-job-api`, `preview-shell`, and `run-results` into the join branch.
- Integrated UI seams:
  - `RunPanel` now matches the shared `RunPanelProps` contract.
  - Failed-job text is shown once, styled as the error sentence.
  - Jest uses a test tsconfig with the `@/` alias.
- Updated README Run section for `pnpm --dir ui install && pnpm --dir ui build` followed by `python3 app.py` / `.venv/bin/python app.py` on `127.0.0.1:8765`.
- Kept generated `ui/dist` out of git while confirming the build writes it.
- Opened draft PR: https://github.com/pedrogritter/sar-tooling-demo/pull/1

## Measurements
- `worker branches merged`: 0 → 3
- `ui Jest tests`: 0 passing → 1 passing
- `tests.test_jobs`: 10 passing == 10 passing
- `unittest discover -s tests`: 5 errors → 23 passing
- `job step_count`: 9 == 9

## Verification
live-ui-verified

## Notes, concerns, deviations, findings, thoughts, feedback
- Ran:
  - `pnpm --dir ui install`
  - `pnpm --dir ui exec tsc --noEmit`
  - `pnpm --dir ui build`
  - `pnpm --dir ui test`
  - `.venv/bin/python -m unittest tests.test_jobs`
  - `.venv/bin/python -m unittest discover -s tests`
  - `.venv/bin/ruff check .`
  - `.venv/bin/mypy`
- `data/stac.json` was absent initially, so I ran `.venv/bin/python scene.py` without `--all`; no GRD/SLC download was started.
- GRD was absent, so the live page pass verified the missing-file failure path.
- Manual recording artifact: 
- The fetched `python-job-api` branch tip already contained a verifier notes commit; the final PR diff excludes the verifier notes file.

## Suggested follow-ups
- Monitor draft PR CI.
- If desired, have a verifier repeat the live pass with GRD present to cover the successful measurement path.