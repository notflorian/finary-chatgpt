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
FINARY_SESSION_PATH=
FINARY_BRIDGE_API_KEY=
FINARY_BRIDGE_URL=
FINARY_GOOGLE_SHEET_ID=
FINARY_SCHEMA_URL=
N8N_ENCRYPTION_KEY=
TZ=Europe/Paris
```

`FINARY_MFA_CODE` should only be used if required by the upstream authentication flow.

Persisted Clerk session state is permitted only for the verified refresh
mechanism. It must contain exactly the minimum session ID and `__client` cookie
value in a protected bridge-only local store. Never persist TOTP secrets,
backup codes, one-time MFA codes, bearer JWTs, browser profiles, or raw
authentication responses. Never expose the session store to n8n, Google Sheets,
ChatGPT, Git, workflow exports, logs, diagnostics, or normal backups.

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
{position_kind}:{asset_id}
finary:{account_id}:asset:{position_kind}:{asset_id}
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
- Live authentication requires a fresh TOTP or email-code challenge to create a
  new Clerk session. `/v1/snapshot` must never prompt interactively. Phase 3
  added no persistence; the later approved Phase 8 store may reuse the minimum
  verified session state but must never persist bearer JWTs, backup codes,
  one-time MFA codes, or TOTP secrets.

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
- Configure every Google Sheets read or preflight node with `Execute Once`.
  Chained reads must never execute once per row returned by the previous sheet,
  because that amplifies API requests as the workbook grows and exhausts the
  per-user Google Sheets quota. Do not apply `Execute Once` to row write nodes.

Definition of done:

- workflow JSON imports successfully into n8n
- running twice with identical input produces no duplicates
- a missing position becomes inactive
- same-day history is updated rather than duplicated
- next-day history creates a new row
- nullable values remain blank rather than becoming zero placeholders
- manual sheets are not overwritten

### Phase 6 - Error handling and operations

Implemented:

- n8n error workflow
- run diagnostics
- last successful synchronization tracking
- documentation for credential rotation
- backup and restore guidance
- failure scenarios
- manual recovery procedure

Phase 5 implementation and live verification established these mandatory
operational constraints, now preserved by Phase 6:

- The main workflow already records sanitized structured bridge failures before
  portfolio writes. The error workflow must cover uncaught n8n, Code node,
  Google Sheets, and mid-write failures without creating duplicate failed
  telemetry for a run that was already recorded.
- Google Sheets enforces per-user read and write request quotas. Every Sheets
  node uses the bounded retry supported by n8n 2.35.5: three total attempts with
  a fixed five-second delay. The installed runtime does not expose native
  exponential backoff. Workflows also have finite execution timeouts, and the
  runbook documents stale-run recovery. A quota increase is not the only
  mitigation.
- Preserve `Execute Once` on every Google Sheets read and preflight node. Add a
  regression check so a preceding sheet with many rows cannot multiply later
  read requests. Write nodes must continue to process every prepared row.
- Sanitize Google and n8n errors before writing `sync_runs` or sending a
  notification. Do not expose spreadsheet IDs, OAuth material, project details,
  raw node payloads, credentials, tokens, cookies, MFA values, or private
  portfolio rows. Use stable error categories and include only a safe failing
  step name when useful.
- Derive the last successful synchronization from the newest `SUCCESS` or
  `SUCCESS_WITH_WARNINGS` telemetry row. A later `FAILED` row must not replace
  or obscure the last-known-valid state.
- A private GitHub repository cannot serve the canonical schema through an
  unauthenticated raw GitHub URL. Provide and document a local, credential-free
  schema-serving path reachable from n8n, and keep
  `docs/google-sheets-schema.json` as the single canonical schema source.
- `docker compose` must start the operational local stack, including n8n with a
  persistent data volume and a network-reachable canonical schema source. Do
  not embed Google OAuth credentials or n8n credential IDs in repository files.
- A new bridge process may require a fresh TOTP or prepared email-code challenge
  when no valid protected Clerk session exists. Document the exact bootstrap,
  restart, expiry, and revocation procedure. HTTP routes must never prompt.
- The verified adapter still has no complete liability feature. Keep the daily
  workflow inactive for production while `/v1/snapshot` returns
  `FINARY_FEATURE_UNAVAILABLE`; Phase 6 must not weaken the contract by treating
  unavailable liabilities as zero merely to enable scheduling.
- The Google Sheets credential must be assigned to every Sheets node on both
  success and failure branches after import. Operations documentation must
  include this check and distinguish credential errors from quota errors.

Definition of done:

- failed Finary authentication does not alter current portfolio data
- malformed snapshots do not overwrite valid current data
- error runs are visible in `sync_runs`
- uncaught n8n and Google Sheets failures produce sanitized, non-duplicated
  diagnostics when telemetry remains writable
- retryable Google Sheets quota and temporary service failures use bounded
  backoff, and executions cannot remain running indefinitely
- the full local stack and canonical schema source start through Docker Compose
- last-success reporting ignores later failed runs and identifies the newest
  valid synchronization
- restart, MFA bootstrap, Google credential assignment, quota recovery, and
  partial-write repair procedures are documented and tested where practical
- the production schedule remains disabled until the bridge can return a
  complete snapshot without fabricating liability coverage
- recovery steps are documented

### Post-Phase-6 operational gates

The user explicitly approved a post-Phase-6 roadmap. Roadmap ordinals 07–13 map
to GitHub issues #13–#19 and are the authoritative next work:

1. #13 — Outcome B completed: no verified complete liability source; schema
   `1.0` remains fail-safe and a future schema `2.0` coverage design is
   documented in `docs/liability-coverage-investigation.md`.
2. #14 — Outcome A completed: a minimal protected Clerk session store was
   implemented and live-verified across fresh clients and a separate process;
   the evidence is documented in `docs/finary-authentication-investigation.md`.
3. #15 — Phase 9 is blocked under schema `1.0`. The authorized live follow-up
   called the organization portfolio overview and credits/accounts surface for
   every discovered membership. Credits were empty and current overview totals
   reconciled, but identity, amount, currency, lifecycle, deduplication,
   pagination, category scope, and authoritative empty semantics remain
   unproven. The recommended next decision is the separately approved schema
   `2.0` migration specified in `docs/schema-v2-migration-plan.md`.
4. #16 — migrate the existing live containers to the repository Compose stack.
5. #17 — add credential-free CI quality gates.
6. #18 — activate production synchronization; blocked by #15, #16, and #17.
7. #19 — connect ChatGPT to the validated workbook; blocked by #18.

These cross-cutting issues are operational milestones, not permission to weaken
the existing contracts. Preserve these gates:

- Keep the production daily workflow inactive while live snapshots fail with
  `FINARY_FEATURE_UNAVAILABLE` because liability coverage is incomplete.
- The error-handler workflow may be published so n8n can select it; it has no
  schedule or external trigger. Do not publish the daily scheduled workflow
  until the activation gates pass.
- Investigate liabilities only against a callable, observed upstream surface.
  Never infer completeness or zero liabilities from empty nested `loans` arrays.
- Preserve the Phase 7 `FinaryRawLiabilities.coverage` distinction. Only
  `COMPLETE` can make an empty collection a known zero; `PARTIAL` and
  `UNAVAILABLE` must remain fail-safe in schema `1.0`.
- Do not implement the recommended schema `2.0` coverage contract without
  explicit approval and a coordinated bridge, Sheets, n8n, telemetry, and
  ChatGPT-semantics migration.
- Preserve the stable downstream schema and isolate upstream changes inside the
  adapter/normalizer wherever possible.
- Preserve the Phase 8 Outcome A boundary. Persist only the verified Clerk
  session ID and `__client` cookie in the bridge-only protected store; keep
  bearer JWTs in memory and never persist TOTP seeds, backup codes, one-time
  factors, browser profiles, mailbox credentials, or raw auth payloads.
- Treat the persisted session as bearer-equivalent, server-revocable, and
  bounded by upstream session expiry. Rejected state must be cleared and return
  `FINARY_AUTH_FAILED`; manual MFA is then required again.
- Require a complete live snapshot and an inactive manual synchronization that
  passes idempotency, totals, history, inactive-row, telemetry, and recovery
  checks before enabling the daily trigger.
- Configure ChatGPT/Google Drive consumption only after a valid workbook state
  exists; never expose Finary credentials or private upstream payloads.

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
   - next roadmap issue and its unmet dependencies

If real Finary behavior conflicts with the documentation, preserve the downstream contract and adapt the bridge.
