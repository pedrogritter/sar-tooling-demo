<!-- orchestrate handoff
task: run-results
branch: orch/scene-web-view/run-results
agentId: bc-080e2617-f2fc-4132-b77e-e7127316400b
runId: run-7d4c5168-9411-4170-abb8-aae183cb5c1d
resultStatus: finished
finishedAt: 2026-11-09T16:56:12.919Z
-->

## Status
success

## Branch
`orch/scene-web-view/run-results`

## What I did
- Added `ui/src/run/RunPanel.tsx` and `ui/src/run/run.css`
  - Starts measurement jobs.
  - Handles 409 as already-running.
  - Polls current job every 400 ms while running.
  - Shows spinner, step count, returned sentence, and failed-job error.
- Added `ui/src/results/ResultsPanel.tsx` and `ui/src/results/results.css`
  - Renders measurement numbers, overview image, return rows, and briefing HTML.
  - Keeps wording to bright returns and does not name a ship.
- Added `ui/src/results/rows.ts`
  - Pure mapper from measurement returns to display rows.
- Added `ui/src/results/rows.test.ts`
  - Jest test with a trimmed fixture copied from `intelligence/measurements.json`.
  - Includes the required top comment naming expected Jest/ts-jest devDependencies because this branch has no `ui/package.json`.
- Committed and pushed:
  - Commit: `8447cb6 Add scene run and results panels`

## Measurements
(none)

## Verification
not-verified

## Notes, concerns, deviations, findings, thoughts, feedback
- I modified only `ui/src/run/**` and `ui/src/results/**`.
- I did not add `package.json`, `main.tsx`, `types.ts`, `api.ts`, or any Python files.
- `ui/package.json` is missing on this branch as expected, so I could not run `pnpm --dir ui build` or Jest locally.
- Static checks run:
  - `git diff --check -- ui` passed.
  - Searched the scoped UI files for forbidden/undesired strings like `ship`, `vessel`, `TODO`, `not implemented`, inline styles, `!important`, and `pnpm dev`; no relevant violations found.
- I did not open a PR per the orchestration instructions.
- No screen recording was captured because the UI is not runnable on this scoped branch without the sibling-owned UI package/bootstrap.

## Suggested follow-ups
- On the integration branch, wire `RunPanel` callbacks into the scene state so completed job results replace the displayed measurement/briefing.
- Run `pnpm --dir ui build` and the Jest test once sibling `ui/package.json`, `@/types`, and `@/api` are present.