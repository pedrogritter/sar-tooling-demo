<!-- orchestrate handoff
task: verify-join-scene-web
branch: `orch/scene-web-view/join-scene-web` (no commits made — verification only; working tree clean, no target source modified)
agentId: bc-505170b7-6315-41da-855f-76560dbaa804
runId: run-161d5cf5-118a-4894-ba0f-5a064ebdcc46
resultStatus: finished
finishedAt: 2026-11-09T18:02:43.718Z
-->

All acceptance criteria verified end-to-end. Here is my verdict.

## Verification
live-ui-verified

## Target
`join-scene-web` on branch `orch/scene-web-view/join-scene-web`

## Branch
`orch/scene-web-view/join-scene-web` (no commits made — verification only; working tree clean, no target source modified)

## Execution
- `git log --graph` / `--merges` → three merge commits present: `c33c3d5` python-job-api, `655a4a6` preview-shell, `d663bdf` run-results, then `d4d55c1` integrate. Verifier branch not merged.
- Env setup: created `.venv` (needed `apt-get install python3.12-venv`), `pip install -r requirements.txt -r requirements-dev.txt` → OK; `pnpm --dir ui install` → OK.
- `pnpm --dir ui exec tsc --noEmit` → exit 0, no errors.
- `pnpm --dir ui build` → built; writes `ui/dist/index.html` (415 B) + hashed `assets/index-*.js|css`.
- `pnpm --dir ui test` (Jest) → 1 passed, 1 suite.
- `.venv/bin/python -m unittest tests.test_jobs -v` → 10 tests OK.
- `.venv/bin/python -m unittest discover -s tests` → initially 5 errors (missing `data/stac.json`); ran `.venv/bin/python scene.py` (no `--all`, no GRD/SLC downloaded) → fetched STAC+quicklook; re-run → 23 tests OK.
- Started `.venv/bin/python app.py` on 127.0.0.1:8765.
- `GET /` → byte-identical to `ui/dist/index.html` (TS page), `Cache-Control: no-store`.
- Hashed `GET /assets/index-*.js` → 200, `Cache-Control: public, max-age=31536000, immutable`. `/quicklook.png` → 200. `/overview.png` → 404 (no overview yet).
- `GET /api/scene` → full STAC facts, `preview_url:/quicklook.png`, `measurement` + `briefing_html` pre-filled from disk, `overview_url:null`.
- `POST /api/jobs/measure` → 202 `{job_id,status:running}`; immediate second POST → 409.
- Polled `/api/jobs/current` → `failed`, `step_count:9`, sentence/error = `Missing data/grd-cog.tif. Run python3 scene.py --all.`, `result:null`; `/api/scene` still 200 with measurement after failure.
- Live browser pass (computerUse): all three regions render, dark radar quicklook loads, results+briefing pre-filled on load, limit line "A row is a bright return, and the page has not named a ship." present; clicking Measure disables button then shows the exact red failure sentence `Missing data/grd-cog.tif. Run python3 scene.py --all.`; preview + results stayed on screen; Network showed polling stopped (no runaway `/current` requests after `failed`). Recording: `/opt/cursor/artifacts/scene-web-view-live-pass-missing-grd.mp4`.
- `gh pr list` → draft PR [#1](https://github.com/pedrogritter/sar-tooling-demo/pull/1) "Integrate scene web view", base `main`, isDraft true.

## Findings
Target acceptance criteria:
- [x] Three worker branches merged; both parents of each slice present: three merge commits in history, verifier branch absent (met)
- [x] `pnpm --dir ui exec tsc --noEmit` passes: exit 0 (met)
- [x] `pnpm --dir ui build` writes `ui/dist/index.html`: present + hashed assets (met)
- [x] `tests.test_jobs` passes; unittest discover run: test_jobs 10 OK; discover 23 OK (met)
- [x] README run section documents `python3 app.py` on 127.0.0.1:8765 and `pnpm --dir ui build`, not `pnpm dev`: README Run section confirmed; no `pnpm dev`, no RAG/LangChain/Ollama/Docker/K8s added (met)
- [x] One pass through http://127.0.0.1:8765: preview shows; measure fails with missing-file sentence; page usable: verified live (met)
- [x] Draft PR opened against main: PR #1, draft, base main (met)

Verifier-specific:
- [x] Verification section includes execution evidence for all criteria: above (met)
- [x] Live page opened on the Python server, not only typecheck: real browser + curl against `python3 app.py`, with screen recording (met)

Other findings:
- (low) No `grd-cog.tif` on disk, so the successful-measurement path (done → numbers/overview replaced) was not exercised; this is the expected/mandated scenario (do not download GRD). The failure path and disk-pre-fill path are fully verified.
- (low) `GET /overview.png` returns 404 and `overview_url` is null because no measurement run has produced `intelligence/overview.png`; consistent with the contract.

## Notes & suggestions
- Environment needed `python3.12-venv` installed via apt before `python3 -m venv` would work; worth baking into env setup.
- All generated artifacts (`.venv`, `data/`, `ui/node_modules`, `ui/dist`) are gitignored; working tree stayed clean. I made no commits (nothing worth committing as a verifier artifact beyond the recording, which lives at `/opt/cursor/artifacts/scene-web-view-live-pass-missing-grd.mp4`).
- Optional follow-up: a verifier run with `python3 scene.py --all` present could cover the successful measurement path (overview image + replaced numbers/briefing after a done job).