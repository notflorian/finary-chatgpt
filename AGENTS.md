# AGENTS.md

## Project

Build a reliable local integration pipeline:

Finary -> finary-bridge -> n8n -> Google Sheets -> ChatGPT

The goal is to make the user's Finary portfolio available to ChatGPT through a structured Google Sheet while keeping Finary credentials out of ChatGPT and Google Sheets.

## Core principles

1. Treat Finary as an unstable upstream dependency.
2. Never let n8n depend directly on Finary's private API schema.
3. Put all Finary-specific parsing and authentication logic inside `finary-bridge`.
4. Expose a stable, versioned internal API from `finary-bridge`.
5. Store normalized portfolio data in Google Sheets.
6. Keep current-state tables separate from append-only history tables.
7. Prefer deterministic identifiers and idempotent synchronization.
8. Never delete historical portfolio rows.
9. Never store Finary credentials in Google Sheets.
10. Never expose Finary credentials to ChatGPT.
11. Keep the system local-first and self-hostable.
12. Make each implementation phase independently testable.

## Repository layout

Target structure:

```text
finary-chatgpt/
├── AGENTS.md
├── README.md
├── .env.example
├── docker-compose.yml
├── finary-bridge/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── finary_client.py
│   │   ├── models.py
│   │   ├── normalizer.py
│   │   └── services/
│   │       └── snapshot_service.py
│   └── tests/
│       ├── test_health.py
│       ├── test_models.py
│       ├── test_normalizer.py
│       └── fixtures/
├── n8n/
│   └── workflows/
│       ├── finary-daily-sync.json
│       └── finary-error-handler.json
└── docs/
    ├── architecture.md
    ├── google-sheets-schema.md
    └── operations.md
```

Do not create files outside this structure unless justified.

## Technology choices

### finary-bridge

Use:

- Python 3.12+
- FastAPI
- Pydantic v2
- Uvicorn
- httpx where HTTP calls are required
- pytest
- ruff
- mypy where practical

Use a Finary client adapter isolated behind an internal interface.

If `finary_uapi` is used, wrap it in `finary_client.py`. No other module should import `finary_uapi` directly.

### n8n

Assume self-hosted n8n.

Use standard n8n nodes where possible:

- Schedule Trigger
- Manual Trigger
- HTTP Request
- Code
- Google Sheets
- Error Trigger

Avoid unnecessary community nodes.

### Google Sheets

Use one workbook named:

`Finary Portfolio Data`

Sheets:

- README
- accounts_current
- positions_current
- liabilities_current
- positions_history
- portfolio_daily
- allocation_targets
- asset_overrides
- cashflows
- sync_runs

## Coding conventions

Code, identifiers, variables, comments, filenames, logs, API field names and commit messages must be in English.

User-facing documentation may be in English unless otherwise requested.

Prefer:

- small functions
- explicit types
- immutable models where practical
- deterministic transformations
- dependency injection for upstream clients
- structured logging
- clear error classes

Avoid:

- global mutable state
- hidden side effects
- hardcoded credentials
- Finary-specific fields leaking into downstream models
- silent error handling
- deleting historical data
- coupling n8n to private Finary response shapes

## Security requirements

Never commit secrets.

Use environment variables:

```text
FINARY_EMAIL=
FINARY_PASSWORD=
FINARY_MFA_CODE=
FINARY_BRIDGE_API_KEY=
N8N_ENCRYPTION_KEY=
TZ=Europe/Paris
```

`FINARY_MFA_CODE` should only be used if required by the upstream authentication flow.

Provide `.env.example` with empty values.

Do not log:

- passwords
- session cookies
- bearer tokens
- MFA secrets
- full raw authentication payloads

The bridge should support an optional internal API key for calls from n8n.

The bridge must not be publicly exposed by default.

## Internal API contract

The bridge must expose:

### GET /health

Response:

```json
{
  "status": "ok",
  "service": "finary-bridge",
  "version": "0.1.0"
}
```

This endpoint must not contact Finary.

### GET /v1/snapshot

Returns the normalized portfolio snapshot described in `docs/architecture.md`.

The endpoint may contact Finary.

It must return normalized data only. Do not expose the raw upstream payload.

### Error format

Use a consistent error response:

```json
{
  "error": {
    "code": "FINARY_AUTH_FAILED",
    "message": "Unable to authenticate with Finary",
    "retryable": false
  }
}
```

Do not include secrets or raw upstream authentication responses.

## Stable downstream models

The bridge owns the translation from private Finary fields to stable internal fields.

At minimum model:

- PortfolioSnapshot
- Account
- Position
- Liability

All monetary amounts sent downstream must include an EUR-normalized value when possible.

Never use display names as primary identifiers.

Prefer stable upstream IDs when available.

Construct downstream keys such as:

```text
finary:account:{account_id}
finary:{account_id}:asset:{asset_id}
finary:liability:{liability_id}
```

## Asset classification

Normalized top-level classes:

```text
EQUITY
BOND
CASH
REAL_ESTATE
SCPI
PRIVATE_EQUITY
CRYPTO
COMMODITY
LIFE_INSURANCE_FUND
OTHER
```

Subclasses may include:

```text
WORLD_EQUITY
US_EQUITY
EURO_EQUITY
EMERGING_EQUITY
EURO_GOV_BOND
EURO_CORP_BOND
GLOBAL_BOND
HIGH_YIELD
CASH_EUR
GOLD
```

Do not make aggressive classification guesses.

When uncertain, use `OTHER` and preserve useful upstream metadata.

Google Sheets `asset_overrides` is authoritative over automatic classification.

## Synchronization behavior

Current-state sheets must use upsert semantics.

History sheets must use date-scoped deterministic keys.

Never delete a position that disappears from a new snapshot.

Instead set:

```text
is_active = FALSE
```

for current-state records that were present previously but are no longer returned.

Historical rows must remain unchanged except when re-running the same day's snapshot with the same deterministic history key.

## Idempotency

Running the same snapshot multiple times must not create duplicate current-state rows.

For daily history, use deterministic keys:

```text
{snapshot_date}:{position_key}
```

For `portfolio_daily`, use:

```text
snapshot_date
```

as the logical unique key.

## Validation gates

Before writing a snapshot downstream, validate:

- snapshot timestamp exists
- currency is present
- account keys are unique
- position keys are unique
- liability keys are unique
- monetary values are finite numbers
- no NaN or infinity values
- position account references are valid
- gross asset total is not negative
- liabilities total is not negative

The synchronization workflow should reject obviously broken snapshots such as:

- zero accounts when previous successful runs had accounts
- empty positions when previous successful runs had positions
- missing required IDs
- duplicate position keys

A large net-worth move should generate a warning rather than automatically fail unless clearly malformed.

Suggested warning threshold:

```text
absolute day-over-day net worth change > 20%
```

## Logging

Use structured logs.

Each synchronization run should have a `run_id`.

Recommended format:

```text
YYYYMMDD-HHMMSS
```

All bridge requests invoked by n8n should accept or generate a correlation identifier.

Do not log private upstream payloads at INFO level.

## Time zone

Use:

```text
Europe/Paris
```

for schedules and business dates.

Store timestamps as ISO 8601 with timezone.

Example:

```text
2026-08-20T07:30:12+02:00
```

## Implementation phases

Codex must implement the project incrementally.

### Phase 1 - Repository bootstrap

Create:

- project structure
- `.env.example`
- Dockerfile
- docker-compose
- FastAPI app
- `/health`
- tests
- lint configuration
- README with local run commands

Definition of done:

- `docker compose up` starts the bridge
- `GET /health` returns HTTP 200
- tests pass
- no Finary integration yet

Do not implement Phase 2 until Phase 1 is working.

### Phase 2 - Finary client adapter

Implement:

- Finary client abstraction
- authentication adapter
- upstream account retrieval
- upstream position retrieval
- upstream liability retrieval if available
- fixture-based tests for upstream normalization

Definition of done:

- Finary-specific code exists only in `finary_client.py` and closely related adapter code
- raw response fixtures can be normalized in tests
- authentication secrets are not logged

If the upstream API differs from expectations, inspect real responses and update fixtures before continuing.

### Phase 3 - Stable snapshot API

Implement:

- Pydantic models
- normalization
- EUR values
- stable keys
- `/v1/snapshot`
- response validation
- structured errors

Definition of done:

- `/v1/snapshot` returns only the stable internal schema
- no private Finary schema leaks to n8n
- tests cover malformed upstream data
- duplicate IDs are rejected

### Phase 4 - Google Sheets schema

Create documentation and initialization helpers for:

- README
- accounts_current
- positions_current
- liabilities_current
- positions_history
- portfolio_daily
- allocation_targets
- asset_overrides
- cashflows
- sync_runs

Definition of done:

- every column is documented
- every sheet has a unique-key strategy
- data types are documented
- sample rows are provided

Do not hardcode a user's financial values in repository fixtures.

### Phase 5 - n8n synchronization workflow

Create importable workflow JSON.

The workflow must:

1. support Manual Trigger
2. support Schedule Trigger
3. call `/v1/snapshot`
4. validate the snapshot
5. read `asset_overrides`
6. apply overrides
7. calculate portfolio totals and weights
8. upsert current accounts
9. upsert current positions
10. mark missing current positions inactive
11. upsert current liabilities
12. upsert daily position history
13. upsert portfolio daily summary
14. append a `sync_runs` record
15. fail safely without destroying previous valid data

Definition of done:

- workflow JSON imports successfully into n8n
- running twice with identical input produces no duplicates
- a missing position becomes inactive
- same-day history is updated rather than duplicated
- next-day history creates a new row

### Phase 6 - Error handling and operations

Add:

- n8n error workflow
- run diagnostics
- last successful synchronization tracking
- documentation for credential rotation
- backup and restore guidance
- failure scenarios
- manual recovery procedure

Definition of done:

- failed Finary authentication does not alter current portfolio data
- malformed snapshots do not overwrite valid current data
- error runs are visible in `sync_runs`
- recovery steps are documented

## What not to implement initially

Do not add these unless explicitly requested:

- public cloud deployment
- public API exposure
- Kubernetes
- Terraform
- Redis
- PostgreSQL
- message queues
- OAuth provider implementation
- custom ChatGPT MCP server
- automated trading
- bank transaction ingestion
- financial recommendation engine

The first goal is reliable portfolio synchronization, not infrastructure complexity.

## Git discipline

Prefer one logical commit per phase or coherent unit.

Suggested commits:

```text
chore: bootstrap finary bridge
feat: add finary client adapter
feat: normalize portfolio snapshot
docs: define google sheets schema
feat: add n8n portfolio sync workflow
feat: add sync validation and monitoring
```

Do not rewrite unrelated files.

Do not make broad architectural changes without explaining why.

## Testing strategy

At minimum:

### Unit tests

- key generation
- Finary-to-internal normalization
- asset classification
- EUR conversion behavior
- malformed input rejection
- totals calculation

### API tests

- health endpoint
- snapshot endpoint success
- snapshot endpoint authentication failure
- malformed upstream payload
- upstream timeout

### Integration tests

Use fixtures and mock upstream calls.

Do not require live Finary credentials for the normal test suite.

A live smoke test may be implemented separately and skipped by default.

## Definition of project success

The project is successful when:

1. Finary can be queried through the bridge.
2. The bridge exposes a stable normalized snapshot.
3. n8n synchronizes it to Google Sheets without duplicates.
4. Current positions reflect the latest state.
5. Historical positions remain available by date.
6. Missing positions are marked inactive rather than deleted.
7. Daily portfolio totals are preserved.
8. ChatGPT can read the Google Sheet and reason over normalized data.
9. Finary credentials never reach Google Sheets or ChatGPT.
10. A Finary upstream schema change can be fixed inside the bridge without changing the downstream schema.

## Instructions for Codex when starting work

Before changing code:

1. Read this file.
2. Read `docs/architecture.md`.
3. Inspect the current repository state.
4. Identify the current implementation phase.
5. Implement only the requested phase unless a small prerequisite is necessary.
6. Run relevant tests and linting.
7. Summarize:
   - files changed
   - tests run
   - unresolved assumptions
   - next recommended phase

If real Finary behavior conflicts with the documentation, preserve the downstream contract and adapt the bridge.
