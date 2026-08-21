# Finary Portfolio Data Bridge

This repository provides a local, self-hosted pipeline for making normalized
Finary portfolio data available to Google Sheets and ChatGPT:

```text
Finary -> finary-bridge -> n8n -> Google Sheets -> ChatGPT
```

Phase 6 implements bounded operational handling, persistent local n8n configuration,
sanitized failure diagnostics, and recovery documentation while
preserving the stable Phase 3 contract at `GET /v1/snapshot` and the canonical
Phase 4 workbook schema. Private Finary response fields remain confined to the
adapter and normalizer.

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

Copy the example environment file and set the local secrets and workbook ID:

```bash
cp .env.example .env
docker compose up --build
```

The bridge and n8n are bound to `127.0.0.1:8000` and `127.0.0.1:5678`. The
canonical schema service is private to the Compose network, and n8n data is
stored in the `n8n_data` named volume. Stop the stack without deleting that
volume with:

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
n8n/workflows/   Importable daily synchronization and error workflows
docs/            Architecture, schema, synchronization, and operations docs
```

## n8n daily synchronization

Import [`n8n/workflows/finary-error-handler.json`](n8n/workflows/finary-error-handler.json)
and then [`n8n/workflows/finary-daily-sync.json`](n8n/workflows/finary-daily-sync.json)
into n8n, assign one Google Sheets OAuth2 credential to every Google Sheets
node, publish the error handler, and link it in the daily workflow Settings.
Publishing the Error Trigger workflow makes it selectable but introduces no
schedule or external endpoint. Compose sets these service URLs by default:

```text
FINARY_GOOGLE_SHEET_ID=<workbook spreadsheet ID>
FINARY_BRIDGE_URL=http://finary-bridge:8000
FINARY_SCHEMA_URL=http://schema-server/google-sheets-schema.json
```

The workflows target n8n 2.35.5. The daily workflow supports a manual trigger
and a daily 07:30 schedule in `Europe/Paris`, but must remain inactive while the
live bridge cannot provide verified liability coverage. The workbook and all
ten sheets must already exist with headers matching the canonical JSON schema. See
[`docs/n8n-daily-sync.md`](docs/n8n-daily-sync.md) for setup, safety semantics,
and status meanings. See [`docs/operations.md`](docs/operations.md)
for monitoring, backups, credential rotation, and recovery.

Phase 6 operational guarantees:

- uncaught node failures flow to `Finary - Error Handler`; handled bridge
  failures remain owned by the daily workflow;
- failure telemetry uses stable Google/auth/quota/temporary/schema/timeout/write
  categories and never stores raw provider errors or portfolio rows;
- the original `YYYYMMDD-HHMMSS` run ID is used only when safely available;
  otherwise the deterministic fallback is `n8n-execution:{execution_id}`;
- an existing terminal `FAILED`, `SUCCESS`, or `SUCCESS_WITH_WARNINGS` row is
  never overwritten by the error handler;
- the last success is the newest valid `completed_at` among `SUCCESS` and
  `SUCCESS_WITH_WARNINGS`, even when newer failures exist;
- Sheets nodes make at most three attempts, five seconds apart. This is the
  bounded fixed-delay policy supported by n8n 2.35.5; authentication, schema,
  snapshot-validation, and deterministic data errors remain terminal after the
  bounded node behavior;
- daily/error executions time out after 300/120 seconds. Read and preflight
  nodes retain `Execute Once`, while write nodes process all rows; repository
  tests guard both sides of that request-amplification invariant;
- Compose runs `finary-bridge`, persistent n8n, and a private canonical-schema
  service on one network. The JSON file in `docs/` remains the single schema
  source of truth.

## Current status and next operational gates

Phases 1 through 6 are implemented; no Phase 7 is currently defined. The daily
production schedule remains disabled because the verified Finary surface does
not provide complete liability coverage, so the live bridge correctly refuses
to publish a misleading snapshot.

Before enabling scheduled synchronization:

1. Verify a supported, structurally understood liability source without
   interpreting empty nested `loans` arrays as zero liabilities.
2. Adapt only the Finary adapter/normalizer and fixtures while preserving schema
   version `1.0`, or explicitly version any unavoidable breaking contract change.
3. Demonstrate repeatable non-interactive authentication using only an upstream-
   supported mechanism; do not persist Clerk cookies, bearer tokens, TOTP
   secrets, or backup codes merely to automate the schedule.
4. Obtain a complete live `/v1/snapshot`, run the inactive workflow manually,
   and verify idempotency, totals, history, inactive-row behavior, and telemetry.
5. Back up n8n and the workbook, then publish the daily schedule only after the
   manual acceptance run succeeds.

ChatGPT/Google Drive access can be configured independently after the workbook
contains a valid synchronized state. It must never receive Finary credentials
or raw private API payloads.

The Google Sheets schema is documented in
[`docs/google-sheets-schema.md`](docs/google-sheets-schema.md). Its canonical,
dependency-free initialization definition is
[`docs/google-sheets-schema.json`](docs/google-sheets-schema.json). The JSON
defines all ten sheet names, ordered headers, types, nullability, ownership,
unique keys, and enum values without calling Google APIs.

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
- The Google Sheets schema and safe initialization definition are implemented.
- The n8n workflow validates the complete snapshot, live workbook headers,
  overrides, and every target row before its first portfolio upsert. It never
  writes `allocation_targets`, `asset_overrides`, or `cashflows`.
- Google credentials and live workbook creation remain intentionally external;
  no OAuth token or spreadsheet content is stored in this repository.

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
