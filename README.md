# Finary Portfolio Data Bridge

This repository will provide a local, self-hosted pipeline for making normalized
Finary portfolio data available to Google Sheets and ChatGPT:

```text
Finary -> finary-bridge -> n8n -> Google Sheets -> ChatGPT
```

Phase 1 implements only the local `finary-bridge` bootstrap and its health
endpoint. It does **not** connect to Finary, authenticate, or expose a
portfolio snapshot yet.

## Prerequisites

- Python 3.12 or newer
- Docker Desktop with Docker Compose (optional, for the container workflow)

## Run locally

```bash
cd finary-bridge
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

In another terminal, verify the bridge:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{
  "status": "ok",
  "service": "finary-bridge",
  "version": "0.1.0"
}
```

## Run with Docker Compose

Copy the example environment file if you want to override the timezone:

```bash
cp .env.example .env
docker compose up --build
```

The bridge is bound to `127.0.0.1:8000`, so it is available to the local host
but not exposed on every network interface. Stop the stack with:

```bash
docker compose down
```

## Quality checks

From `finary-bridge` with the virtual environment active:

```bash
python -m pytest
python -m ruff check .
python -m mypy app
```

## Repository layout

```text
finary-bridge/   Local FastAPI bridge and its tests
n8n/workflows/   Reserved for Phase 5 synchronization workflows
docs/            Architecture and future operational documentation
```

## Security and scope

- Keep `.env` local; it is ignored by Git.
- Never add Finary credentials to Google Sheets, ChatGPT, logs, or commits.
- The only implemented HTTP endpoint is `GET /health`; it has no upstream
  dependencies.
- `GET /v1/snapshot`, Finary authentication, data normalization, and n8n
  workflows are intentionally deferred to later phases.
