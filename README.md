# Lisbon spotlight scene

Public ICEYE scene `ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF`, from the [ICEYE open data catalogue](https://www.iceye.com/open-data-initiative), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This repository does not include the radar files.

Collected 24 October 2025, 13:53 UTC, by ICEYE-X52. Spotlight, X-band, VV. The footprint covers the 25 de Abril bridge. The package name is `scene`. This checkout points `src/scene/fetch.py` at this collect, and `content/scene_note.md` is the note for it.

## Layout

| Path | Role |
| --- | --- |
| `src/scene/` | Python package: fetch the STAC assets, measure them, and serve the page |
| `frontend/` | Vite and React page. `pnpm --dir frontend build` writes `frontend/dist` |
| `content/scene_note.md` | Person-written note shown on the fallback page |
| `data/` | Downloaded scenes in `data/scenes/<id>/`, plus the catalog index. Gitignored |
| `intelligence/` | Measurement outputs. `overview.png` is gitignored |
| `tests/` | Python tests |

## Run

Run these from the repository root, the directory that contains `pyproject.toml`.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
.venv/bin/python -m scene.fetch
pnpm --dir frontend install
pnpm --dir frontend build
.venv/bin/python -m scene.serve
```

`python` and `python3` are not the same program here. `python` is `/usr/bin/python`, Python 2.7. `python3` is Python 3.12, and `python3 -m venv .venv` builds the virtualenv from that interpreter. `.venv/bin/pip install -e .` then installs the `scene` package into that virtualenv only. Creating the virtualenv does not change what the command `python` means, and the README does not activate it, so a later `python -m scene.fetch` still runs Python 2.7. That interpreter has no `scene` install, and from the repository root it cannot see `src/scene` either, so it stops with `No module named scene`.

From inside `src/`, the same `python` does find the folder named `scene`, because the current directory is on the import path. It then fails on the first Python 3 annotation (`west: float`). The package requires Python 3.12. Call it as `.venv/bin/python`, which is the interpreter the install used.

Open http://127.0.0.1:8765. `SCENE_HOST` and `SCENE_PORT` change that address. The product command is `.venv/bin/python -m scene.serve`. `pnpm --dir frontend build` writes `frontend/dist`, and the Python process serves that page.

The page is one canvas. A labeled tool column sits on the left, the selected scene fills the center, and the chosen tool opens one pane on the right. Preview chooses the quicklook, thumbnail, or dwell video. The analysis groups run a tool on the open scene and put its picture on the stage. Catalog and Library search and open scenes. Facts float on the picture and can be hidden. A download lists each file and its byte count along the bottom. Click the same tool, Close, or Escape to shut the pane.

`.venv/bin/python -m scene.fetch` saves the Lisbon test scene under `data/scenes/<id>/`: the STAC record, the thumbnail, the quicklook, and the dwell video. `.venv/bin/python -m scene.fetch --all` also streams the GRD (about 484 MB), the colorized sub-aperture image (about 1.2 GB), the georeferenced dwell stack (about 827 MB), and the SLC (about 11 GB). The catalogue URL for that test scene lives in `src/scene/fetch.py`. A flat `data/stac.json` checkout is moved into the scene folder on startup, so files already on disk are not fetched again.

The catalog tool searches the [ICEYE open data collection](https://iceye-open-data-catalog.s3.amazonaws.com/collections/iceye-sar.json). That bucket is a static STAC catalog, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), with no account. The commercial [ICAS catalog](https://docs.iceye.com/constellation/api/catalog/) is not called: it needs client credentials, and a download there is a purchase. The first search reads the collection link list. Item JSON (footprint, mode, thumbnail) fills in behind that list and is cached in `data/catalog-index.json` for 24 hours. The default download is the preview pack: thumbnail, quicklook, quicklook metadata, and the dwell video when the item has it, plus the STAC record. Large products stay unchecked until someone selects them. One download runs at a time.

When `frontend/dist/index.html` is missing, `GET /` serves the original Python page: the quicklook, the STAC fields, and the person-written `content/scene_note.md`. When the build exists, choosing a scene shows its quicklook until an analysis picture replaces it.

The measure control in the tool column is the analysis belt. Each tool reads rasters already on disk and draws a decibel picture with a legend. A tool the scene cannot support stays in the belt and names the missing file or the missing second look. The older Lisbon-only job is still available as `POST /api/jobs/measure`.

The same measurement from the shell, for the Lisbon test scene only:

```bash
.venv/bin/python -m scene.analyze
```

That requires the GRD and the dwell stack on disk. It writes:

| File | Contents |
| --- | --- |
| `intelligence/measurements.json` | Water area, deck return, and bright returns |
| `intelligence/returns.geojson` | The same returns as points, plus the deck line |
| `intelligence/overview.png` | Water tint and deck line on the radar image |
| `intelligence/briefing.md` | Prose from the measurement file |

`overview.png` is produced locally and is not stored in git. Set `OPENAI_API_KEY` in the environment or in a gitignored `.env` to let the model phrase `briefing.md` from `measurements.json` only.

## What the page may claim

The quicklook, the STAC fields printed beside it, the measurement numbers, the overview, and the briefing. A row is a bright return, and the page has not named a ship. The fallback Python page also shows `content/scene_note.md`, which a person wrote.

## What this repository does not do

- No named vessel, no AIS, and no fusion with another sensor. A square in `intelligence/overview.png` is a bright radar return.
- No claim that a model read the radar. `.venv/bin/python -m scene.analyze` calls a model only when `OPENAI_API_KEY` is set, and the prompt may only phrase `measurements.json`.
- More than one open-data scene can be stored under `data/scenes/`. The bridge measurement runs only on the Lisbon test scene. No change detection and no map library. The quicklook stays in the product's own pixel orientation. No ICAS purchase.
- Python here is this reader, this job, and this page. It is not a large service other people depend on.
- No Kubernetes. No air-gapped or classified deploy. Files already on disk and a local process are an offline view of the scenes downloaded here, nothing more.
- No LangChain and no LangGraph. A later answer, if the page is right, has to work in plain Python over the STAC fields and the note before any framework wraps it.
- No defense customer and no live track match. The scene is ICEYE open data.
- GIS employment is not represented here. The note is a personal reading of one open scene.

Docker is not in this slice. The next piece, after this page is the one worth showing, is one container and one command.

## Tests

Development checks need ruff and mypy:

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests
.venv/bin/ruff check .
.venv/bin/mypy
pnpm --dir frontend typecheck
pnpm --dir frontend test
```
