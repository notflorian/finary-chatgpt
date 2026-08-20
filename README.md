# Finary Portfolio Data Bridge

This repository will provide a local, self-hosted pipeline for making normalized
Finary portfolio data available to Google Sheets and ChatGPT:

```text
Finary -> finary-bridge -> n8n -> Google Sheets -> ChatGPT
```

Phase 3 adds a stable, versioned normalized portfolio contract at
`GET /v1/snapshot`. Private Finary response fields remain confined to the
adapter and normalizer; Google Sheets and n8n remain deferred.

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

The snapshot endpoint is:

```bash
curl http://127.0.0.1:8000/v1/snapshot
```

The current live adapter intentionally returns a structured
`FINARY_FEATURE_UNAVAILABLE` error because Finary liability coverage has not
been verified. It does not publish zero liabilities or a misleading net worth.
A successful snapshot is available to deterministic injected clients that
explicitly provide a complete liability collection, including a known-empty
collection.

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
- `GET /health` has no upstream dependencies and never creates a Finary client.
- `GET /v1/snapshot` returns only strict Pydantic models with schema version
  `1.0`, category-aware keys, allowlisted fields, and sanitized errors.
- Finary credentials are read from `FINARY_EMAIL`, `FINARY_PASSWORD`, and the
  optional `FINARY_MFA_CODE` environment variable.
- The private API surface was verified against `finary_uapi` 0.2.3. The bridge
  uses `curl-cffi` directly because that library's helper persists JWT/cookie
  files and may debug-log complete entity payloads; neither behavior is suitable
  for this service boundary.
- Authentication uses the verified Clerk password flow with TOTP or prepared
  email-code challenges and retains cookies and the bearer token in memory only.
- The adapter retrieves holding accounts and the verified asset collections
  for securities, crypto, euro funds, crowdlending, generic assets, precious
  metals, real estate, SCPI, and startups.
- The verified upstream client surface does not provide a callable liability
  endpoint. Live account, real-estate, and SCPI payloads exposed nested `loans`
  arrays, but all observed arrays were empty, so their element schema and
  duplication behavior remain unverified. The adapter therefore reports
  liabilities through an explicit unavailable-feature exception instead of
  fabricating an extraction rule.
- Gross assets use non-collection account balances only. Position values are
  never added to account balances, preventing double counting.
- EUR fields are populated only from amounts whose associated currency is
  explicitly `EUR`; `display_*` values are never assumed to be EUR.
- Downstream `metadata` is currently an empty allowlist. No raw institution,
  account, valuable, address, description, or correlation data is copied.
- Google Sheets and n8n workflows remain intentionally deferred.

## Optional live adapter smoke test

The normal test suite uses anonymized fixtures and never contacts Finary. To
run the separate live structural smoke test deliberately, provide credentials
locally and set the explicit opt-in flag:

```bash
FINARY_LIVE_TEST=1 python -m pytest -m live tests/live -s --tb=no
```

If Clerk requires an email-code or TOTP challenge, the live test prompts for
the one-time code after starting the same in-memory authentication attempt. The
code is not stored or logged.

Set `FINARY_LIVE_DESCRIBE=1` for a sanitized structural report containing only
record counts, top-level field names, and JSON types. It never prints field
values or raw payloads.

The smoke test does not print upstream payloads or financial values.
