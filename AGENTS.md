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

Phase 2 live verification established these mandatory normalization constraints:

- Finary account IDs are strings, while position IDs may be numeric. Convert
  every upstream identifier to a canonical string before key generation.
- Position IDs come from separate asset-category namespaces. Include the
  adapter position kind in `source_asset_id` or `position_key` so equal numeric
  IDs from different categories cannot collide.
- Use the dedicated adapter position collections as the canonical position
  source. Do not also normalize asset arrays nested inside account records,
  because that would double-count the same upstream holdings.
- Link positions to accounts using the verified `holdings_account_id` field.
  Treat nested `account` and `bank_account` objects as non-authoritative
  upstream details unless a fixture proves a required fallback.
- Do not assume fields prefixed with `display_` are EUR. An amount may populate
  an `*_eur` field only when its currency provenance proves it is EUR or a
  verified FX conversion is available. Reject a snapshot whose totals cannot
  be normalized reliably instead of silently relabeling or omitting amounts.
- Select and document exactly one gross-assets source and explicit exclusion
  rules for aggregate or collection accounts. Never sum both account balances
  and position values into gross assets.
- Metadata exposed downstream must use an explicit allowlist of stable,
  non-sensitive keys. Never copy complete upstream records, nested institution
  objects, account identifiers, addresses, or raw private payloads into
  `metadata`.
- The verified upstream surface has no usable liability representation yet.
  Empty embedded `loans` arrays do not prove that liabilities are zero. Map the
  adapter's unavailable-feature error to a structured API error; do not publish
  `liabilities_eur = 0` or a net-worth figure as if liability coverage were
  complete.
- Live authentication requires a fresh TOTP or email-code challenge for a new
  in-memory Clerk session. `/v1/snapshot` must never prompt interactively.
  Authentication/session lifetime must be dependency-injected and documented;
  do not persist cookies, bearer tokens, backup codes, or TOTP secrets as part
  of Phase 3.

Definition of done:

- `/v1/snapshot` returns only the stable internal schema
- no private Finary schema leaks to n8n
- tests cover malformed upstream data
- duplicate IDs are rejected
- tests cover equal numeric position IDs in different asset categories
- tests prove account and nested position data are not double-counted
- every populated EUR field has verified currency provenance
- unavailable liabilities produce an explicit structured error rather than a
  misleading zero-liability snapshot

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

Phase 4 must preserve the implemented Phase 3 contract:

- Treat `source_asset_id` and `position_key` as category-aware identifiers;
  never remove the position kind from either key.
- Allow position currency and EUR-derived fields to be blank when Phase 3
  cannot prove EUR provenance. Do not coerce unknown amounts to zero or infer
  EUR from `display_*` values.
- Treat a structured snapshot error as the absence of a complete snapshot.
  In particular, unavailable liability coverage must not create zero-valued
  liability or net-worth rows, and must not overwrite prior valid data.
- Keep account balances as the authoritative source for gross assets. Position
  values are analytical components and must not be added to account balances.
- Keep the metadata allowlist empty unless a later verified contract change
  explicitly introduces stable, non-sensitive metadata fields.
- Document automated, manual, nullable, and derived columns distinctly so the
  later n8n workflow can preserve null semantics and ownership boundaries.

Definition of done:

- every column is documented
- every sheet has a unique-key strategy
- data types are documented
- nullable fields and unknown-value behavior are documented
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

Phase 5 must use `docs/google-sheets-schema.json` as the canonical source for
sheet names, ordered headers, types, ownership, nullability, enums, and key
formats. It must preserve these Phase 4 rules:

- Validate the complete snapshot and all derived rows before any portfolio
  write. A structured bridge error may append failed `sync_runs` telemetry but
  must not update, clear, or deactivate portfolio rows.
- Preserve blank cells as unknown values. Never coerce a nullable currency or
  numeric field to zero, `N/A`, `unknown`, or the text `null`.
- Copy the authoritative Phase 3 `gross_assets_eur` account-balance total and
  use account balances only for consistency checking. Never add position values
  to account balances.
- Calculate position weights and asset-class percentages only over active
  positions with known `market_value_eur`. Treat the result as known-EUR
  coverage, not full gross-portfolio reconciliation, when any active position
  lacks a verified EUR value.
- Do not write `portfolio_daily` or current/history portfolio rows from an
  incomplete snapshot. Unavailable liability coverage is not zero liabilities
  and must not create a synthetic net worth.
- Never overwrite the manual `allocation_targets`, `asset_overrides`, or
  `cashflows` sheets. Apply enabled overrides using the documented exact-match
  precedence and reject ambiguous matches.
- Use decimal fractions for percentages, `TRUE`/`FALSE` for booleans,
  Europe/Paris business dates, and timezone-aware ISO 8601 timestamps.
- Preserve all category-aware IDs and deterministic current/history/daily keys
  exactly as defined in the Phase 4 schema.

Definition of done:

- workflow JSON imports successfully into n8n
- running twice with identical input produces no duplicates
- a missing position becomes inactive
- same-day history is updated rather than duplicated
- next-day history creates a new row
- nullable values remain blank rather than becoming zero placeholders
- manual sheets are not overwritten

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
