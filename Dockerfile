# One process: the Python server and the built page.
# Radar files are not copied in. An empty /app/data volume is seeded at start.

FROM node:26.13.0-bookworm AS ui

WORKDIR /src/frontend
# Node 26 images no longer ship corepack. This is the pnpm binary, not an npm install of the app.
RUN curl -fsSL "https://github.com/pnpm/pnpm/releases/download/v10.7.0/pnpm-linux-x64" -o /usr/local/bin/pnpm \
    && chmod +x /usr/local/bin/pnpm \
    && pnpm --version
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/.nvmrc ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY src ./src
COPY content ./content
COPY demo ./demo
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e .
COPY --from=ui /src/frontend/dist ./frontend/dist
RUN python demo/build_seed.py

ENV SCENE_HOST=0.0.0.0 \
    SCENE_PORT=8765 \
    PYTHONUNBUFFERED=1
EXPOSE 8765
VOLUME ["/app/data"]
CMD ["python", "-m", "scene.serve"]
