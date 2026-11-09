# Lisbon spotlight scene

Public ICEYE scene `ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF`.

Collected 24 October 2025, 13:53 UTC, by ICEYE-X52. Spotlight, X-band, VV. The footprint covers the 25 de Abril bridge.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
python3 scene.py
.venv/bin/python app.py
```

Open http://127.0.0.1:8765

`python3 scene.py` saves the STAC record, the thumbnail, the 4 MB quicklook, and the 16 MB dwell video. `python3 scene.py --all` also streams the GRD, the colorized sub-aperture image, the georeferenced dwell stack, and the SLC. `.venv/bin/python analyze.py` measures the GRD and the dwell stack and writes `intelligence/`.

The page is one Python process. It reads `data/stac.json`, renders `data/qlk-cog.tif` to a PNG, and shows `scene_note.md`.

## What the page may claim

The quicklook, the STAC fields printed beside it, and the scene note. The note was written by a person. The page says so.

## What this repository does not do

- No named vessel, no AIS, and no fusion with another sensor. A square in `intelligence/overview.png` is a bright radar return.
- No claim that a model read the radar. `analyze.py` calls a model only when `OPENAI_API_KEY` is set, and the prompt may only phrase `measurements.json`.
- No second scene, no change detection, and no map library. The quicklook stays in the product's own pixel orientation.
- Python here is this reader and this page. It is not a large service other people depend on.
- No Kubernetes. No air-gapped or classified deploy. Files already on disk and a local process are an offline view of this one scene, nothing more.
- No LangChain and no LangGraph. A later answer, if the page is right, has to work in plain Python over the STAC fields and the note before any framework wraps it.
- No defense customer and no live track match. The scene is ICEYE open data.
- GIS employment is not represented here. The note is a personal reading of one open scene.

Docker is not in this slice. The next piece, after this page is the one worth showing, is one container and one command.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/ruff check .
.venv/bin/mypy
```
