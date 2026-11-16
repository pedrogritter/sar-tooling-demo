<a id="readme-top"></a>

<h1 align="center">SAR Toolkit</h1>

<p align="center">This viewer exists so a person can search the public ICEYE catalogue, download a scene onto this machine, and measure only what the rasters support.</p>

<p align="center">A bright mark is a bright radar return.</p>

<p align="center"><a href="#what-it-does">What it does</a> · <a href="#quick-start">Quick start</a> · <a href="#develop">Develop</a> · <a href="#tests">Tests</a> · <a href="docs/application.md">Careful claims</a></p>

<!-- Screenshot: the scene stage with the Lisbon quicklook and the tool column. -->

<p align="center"><em>Screenshot to capture: the scene stage with the Lisbon quicklook and the tool column.</em></p>

<details>
<summary>Table of contents</summary>

- [What it does](#what-it-does)
- [Pictures still to capture](#pictures-still-to-capture)
- [Quick start](#quick-start)
- [Develop](#develop)
- [Configuration](#configuration)
- [Tests](#tests)
- [Where the careful claims live](#where-the-careful-claims-live)
- [Status](#status)

</details>

## What it does

Open a public ICEYE scene on a local page. The built-in example is the Lisbon spotlight collect `ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF` (ICEYE-X52, 24 October 2025, 25 de Abril bridge).

The radar files stay out of git. The scene and the catalogue are from the [ICEYE open data catalogue](https://www.iceye.com/open-data-initiative), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

| Goal | What this page does |
| --- | --- |
| See a scene without the rasters | Docker copies the committed Lisbon preview, thumbnail, dwell video, and analysis. |
| Find another collect | Search the public catalogue. A row is labeled with the nearest place. |
| Bring a scene onto this machine | Download the files you select. Large rasters stay unchecked until you ask for them. |
| Measure | Run a toolkit tool when the rasters for that tool are on disk. |
| Read the limit | Every result says what the number is not. Those sentences live in the docs, not here. |

<p align="right"><a href="#readme-top">Back to top</a></p>

## Pictures still to capture

<!-- Screenshot: one finished toolkit result, the picture and the limit sentence together. -->

<p align="center"><em>Screenshot to capture: one finished toolkit result, the picture and the limit sentence together.</em></p>

<!-- Screenshot: the catalog row list, with a place name visible. -->

<p align="center"><em>Screenshot to capture: the catalog row list, with a place name visible.</em></p>

<p align="right"><a href="#readme-top">Back to top</a></p>

## Quick start

From a fresh clone:

```bash
docker compose up --build
```

Open http://127.0.0.1:8765. The page shows the committed Lisbon preview, thumbnail, dwell video, and analysis results. The image does not contain a GRD, an SLC, a colorized image, a dwell stack, or a quicklook COG.

Seeding, the drawn placeholder, and `docker compose down -v` are described in [docs/application.md](docs/application.md).

<p align="right"><a href="#readme-top">Back to top</a></p>

## Develop

Python 3.12 and pnpm. Run these from the repository root, the directory that contains `pyproject.toml`. If `python` on the machine is older, create the environment with `python3`. After that, call `.venv/bin/python`.

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

<p align="right"><a href="#readme-top">Back to top</a></p>

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

<p align="right"><a href="#readme-top">Back to top</a></p>

## Where the careful claims live

The toolkit table and the claim limits stay in [docs/application.md](docs/application.md). That file is the memory. This page does not copy it.

## Status

Version 0.1.0. The scene and the catalogue are [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). No code licence is declared. How to work on the code is the Development section of [docs/application.md](docs/application.md).

<p align="right"><a href="#readme-top">Back to top</a></p>
