# Lisbon spotlight scene

Public ICEYE scene `ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF`, from the [ICEYE open data catalogue](https://www.iceye.com/open-data-initiative), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This repository does not include the radar files.

Collected 24 October 2025, 13:53 UTC, by ICEYE-X52. Spotlight, X-band, VV. The footprint covers the 25 de Abril bridge.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
python3 scene.py
pnpm --dir ui install
pnpm --dir ui build
.venv/bin/python app.py
```

Open http://127.0.0.1:8765. `SCENE_HOST` and `SCENE_PORT` change that address. The product command is `.venv/bin/python app.py`. `pnpm --dir ui build` writes `ui/dist`, and the Python process serves that page.

`python3 scene.py` saves the STAC record, the thumbnail, the quicklook, and the dwell video. `python3 scene.py --all` also streams the GRD (about 484 MB), the colorized sub-aperture image (about 1.2 GB), the georeferenced dwell stack (about 827 MB), and the SLC (about 11 GB).

When `ui/dist/index.html` is missing, `GET /` serves the original Python page: the quicklook, the STAC fields, and the person-written `scene_note.md`. When the build exists, the page shows the quicklook and the STAC facts, and it fills the results from `intelligence/` if a measurement is already on disk.

The measure button starts one background job. The page shows that job's step sentence until it finishes, then replaces the numbers, the overview, and the briefing. A second click while a job is running is refused. If `data/grd-cog.tif` or `data/vid-cog.tif` is missing, the job fails and names `python3 scene.py --all`. The button does not download those files.

The same measurement from the shell:

```bash
.venv/bin/python analyze.py
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

The quicklook, the STAC fields printed beside it, the measurement numbers, the overview, and the briefing. A row is a bright return, and the page has not named a ship. The fallback Python page also shows `scene_note.md`, which a person wrote.

## What this repository does not do

- No named vessel, no AIS, and no fusion with another sensor. A square in `intelligence/overview.png` is a bright radar return.
- No claim that a model read the radar. `analyze.py` calls a model only when `OPENAI_API_KEY` is set, and the prompt may only phrase `measurements.json`.
- No second scene, no change detection, and no map library. The quicklook stays in the product's own pixel orientation.
- Python here is this reader, this job, and this page. It is not a large service other people depend on.
- No Kubernetes. No air-gapped or classified deploy. Files already on disk and a local process are an offline view of this one scene, nothing more.
- No LangChain and no LangGraph. A later answer, if the page is right, has to work in plain Python over the STAC fields and the note before any framework wraps it.
- No defense customer and no live track match. The scene is ICEYE open data.
- GIS employment is not represented here. The note is a personal reading of one open scene.

Docker is not in this slice. The next piece, after this page is the one worth showing, is one container and one command.

## Tests

Development checks need ruff and mypy:

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests
.venv/bin/ruff check .
.venv/bin/mypy
pnpm --dir ui typecheck
pnpm --dir ui test
```
