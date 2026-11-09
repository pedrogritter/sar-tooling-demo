<!-- orchestrate handoff
task: preview-shell
branch: orch/scene-web-view/preview-shell
agentId: bc-95c39100-96b1-47f8-9d53-efd76d2e5f60
runId: run-74a0649f-4258-4420-9fd4-c2f9b067d142
resultStatus: finished
finishedAt: 2026-11-09T16:56:43.250Z
-->

## Status
success

## Branch
`orch/scene-web-view/preview-shell`

## What I did
- Added new `ui/` Vite/React/TypeScript package with pnpm lockfile.
- Added `@/` alias in Vite and TypeScript configs.
- Added shared API contract in `ui/src/types.ts`.
- Added same-origin API helpers in `ui/src/api.ts`.
- Added `main.tsx` that fetches `/api/scene`, installs `/client-error` reporting, mounts preview/run/results regions, imports `RunPanel` and `ResultsPanel` without creating them.
- Added preview region component and BEM stylesheet.
- Added global page chrome stylesheet preserving paper/dark radar direction and serif briefing setup.
- Added Jest config and scripts.

## Measurements
(none)

## Verification
not-verified

## Notes, concerns, deviations, findings, thoughts, feedback
- `pnpm --dir ui install --frozen-lockfile` passes.
- `pnpm --dir ui test` passes with no tests found.
- `pnpm --dir ui typecheck` and `pnpm --dir ui build` fail only on the expected missing sibling modules:
  - `@/run/RunPanel`
  - `@/results/ResultsPanel`
- No Python files, README, tests, `ui/src/run/**`, or `ui/src/results/**` were modified.
- No PR opened, per worker instruction.
- Branch was pushed to origin.

## Suggested follow-ups
- Join with the run/results chunks, then rerun `pnpm --dir ui typecheck` and `pnpm --dir ui build`.
- Add the sibling fixture tests under `ui/src/**/*.test.ts` once ResultsPanel exists.