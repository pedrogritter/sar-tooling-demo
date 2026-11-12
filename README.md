# sar-tooling-demo

Local viewer for ICEYE open-data SAR. A person can search the public catalogue, download a scene onto this machine, and measure only what the rasters support.

The built-in example is the Lisbon spotlight collect `ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF` (ICEYE-X52, 24 October 2025, 25 de Abril bridge). The radar files are not in git. The scene and the catalogue are from the [ICEYE open data catalogue](https://www.iceye.com/open-data-initiative), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Architecture, what the page may claim, and how the pieces fit are in [docs/application.md](docs/application.md).

## Quickstart

From a fresh clone:

```bash
docker compose up --build
```

Open http://127.0.0.1:8765. The page shows the committed Lisbon preview, thumbnail, dwell video, and analysis results. The image does not contain a GRD, an SLC, a colorized image, a dwell stack, or a quicklook COG.

Seeding, the drawn placeholder, and `docker compose down -v` are described in [docs/application.md](docs/application.md).

## Develop

Run these from the repository root, the directory that contains `pyproject.toml`. On this machine `python` is Python 2.7 and `python3` is 3.12. Call `.venv/bin/python`.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
.venv/bin/python -m scene.fetch
pnpm --dir frontend install
pnpm --dir frontend build
.venv/bin/python -m scene.serve
```

Open http://127.0.0.1:8765.

The Lisbon measurement from the shell requires the GRD and the dwell stack on disk:

```bash
.venv/bin/python -m scene.analyze
```

It writes `intelligence/measurements.json`, `intelligence/returns.geojson`, `intelligence/overview.png`, and `intelligence/briefing.md`. `overview.png` is gitignored.

## Configuration

`OPENAI_API_KEY` is optional. Set it in the shell, or in a gitignored `.env` next to `docker-compose.yml`, before `docker compose up`. If it is missing, Start still measures. `SCENE_HOST` and `SCENE_PORT` change the address. The published port is 8765.

Effects are in the Configure table in [docs/application.md](docs/application.md).

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests
.venv/bin/ruff check .
.venv/bin/mypy
pnpm --dir frontend typecheck
pnpm --dir frontend test
```

## Status

Version 0.1.0. The scene and the catalogue are [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). No code license is declared. How to work on the code is the Development section of [docs/application.md](docs/application.md).
