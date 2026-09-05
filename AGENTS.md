# AGENTS.md

## Mission

Maintain a reliable local integration pipeline:

```text
Finary -> finary-bridge -> n8n -> Google Sheets -> ChatGPT
```

The bridge isolates Finary's private API and exposes stable normalized data.
n8n validates and synchronizes that data into a deterministic analytical
workbook. ChatGPT reads the workbook without receiving Finary credentials or raw
upstream payloads.

## Start every task

Before changing code or documentation:

1. Read this file and `docs/architecture.md`.
2. Inspect the repository, tests, and working-tree status.
3. Treat implemented code, fixtures, and `docs/google-sheets-schema.json` as more
   authoritative than prose that conflicts with them.
4. Keep the requested scope narrow and preserve unrelated user changes.
5. Run checks proportional to the change and inspect the final diff.

## Repository map

```text
finary-chatgpt/
├── AGENTS.md
├── README.md
├── LICENSE
├── .env.example
├── docker-compose.yml
├── finary-bridge/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── finary_client.py
│   │   ├── finary_session_store.py
│   │   ├── models.py
│   │   ├── normalizer.py
│   │   └── services/snapshot_service.py
│   └── tests/
├── n8n/workflows/
│   ├── finary-daily-sync.json
│   └── finary-error-handler.json
├── scripts/
└── docs/
    ├── architecture.md
    ├── data-model.md
    ├── operations.md
    ├── chatgpt.md
    ├── development.md
    ├── finary-portfolio-data-knowledge.md
    └── google-sheets-schema.json
```

Do not add new top-level structure without a clear architectural reason.

## Technical baseline

- Python 3.12+, FastAPI, Pydantic v2, Uvicorn
- `curl-cffi` inside the Finary adapter
- pytest, Ruff, mypy
- self-hosted n8n using standard nodes
- Google Sheets schema `2.1`
- `Europe/Paris` schedules and business dates
- ISO 8601 timestamps with explicit timezone offsets

Code, identifiers, comments, filenames, logs, API fields, and commit messages
must be in English. Prefer small typed functions, immutable models where useful,
dependency injection, deterministic transformations, and structured logging.

## Architectural boundaries

### Finary adapter

All private Finary authentication, endpoints, response shapes, and exception
translation belong in `finary_client.py`, `finary_session_store.py`, or a closely
related adapter module. No other module may import an upstream Finary library or
depend on raw response schemas.

Do not invent endpoints, fields, authentication flows, pagination, currencies,
or liability support. Base adapter changes on the installed client, upstream
source, anonymized fixtures, or an explicitly authorized live check.

### Normalization

`normalizer.py` performs pure category-specific transformations. The snapshot
service orchestrates adapter calls, cross-reference validation, totals, and
stable model construction. FastAPI route functions remain HTTP boundaries only.

Use dedicated adapter position collections as the canonical position source.
Never also normalize nested account asset arrays. Associate positions only with
the verified `holdings_account_id`; do not silently fall back to nested account
objects.

Canonical keys are:

```text
account_key     = finary:account:{account_id}
source_asset_id = {position_kind}:{asset_id}
position_key    = finary:{account_id}:asset:{position_kind}:{asset_id}
history_key     = {snapshot_date}:{position_key}
```

Canonicalize upstream identifiers to strings. Position kind is mandatory
because numeric IDs can collide across Finary collections.

### Currency and totals

Populate an `*_eur` field only when currency provenance proves EUR or a verified
conversion exists. Never treat `display_*` fields as proof of EUR. Preserve
unknown numeric values as null/blank, not zero or text placeholders. Reject
non-finite values.

Non-collection account balances are authoritative for `gross_assets_eur`.
Positions are analytical components. Never add position totals to account
balances.

Liability coverage is explicit: `COMPLETE`, `PARTIAL`, or `UNAVAILABLE`. Only
`COMPLETE` can establish liability totals or update liability current state.
Empty embedded loan arrays do not prove zero liabilities. With incomplete
coverage, liabilities and net worth remain null.

Classify assets conservatively. Do not guess from names or tickers. The stable
top-level classes are defined by `AssetClass`; enabled `asset_overrides` rows are
authoritative after normalization.

### Stable API

- `GET /health` returns service metadata without contacting Finary or reading
  authentication state.
- `GET /v2/snapshot` is canonical and returns schema `2.0` normalized data with
  explicit liability coverage.
- `GET /v1/snapshot` is a strict legacy route that remains fail-safe when a
  complete snapshot cannot be built.
- Structured errors use `{error: {code, message, retryable}}` and never expose
  raw upstream details.

Keep `/v2/snapshot` backward compatible within schema major version `2`. Make a
coordinated schema, workflow, workbook, tests, and documentation change for any
breaking downstream contract revision.

### Google Sheets and n8n

`docs/google-sheets-schema.json` is the single machine-readable workbook
contract. Preserve its sheet order, headers, types, nullability, ownership,
enums, and key formats. Documentation summarizes it but must not become a second
field-level source of truth.

Current sheets use deterministic upserts. Missing accounts or positions become
`is_active = FALSE`; they are not deleted. Historical rows are never deleted,
and same-day history uses `history_key` to update rather than duplicate.

The synchronization workflow must validate the complete snapshot and prepared
rows before portfolio writes. A failed or malformed snapshot may write sanitized
`sync_runs` telemetry but must not alter the last valid portfolio state.

Never overwrite the manual `allocation_targets`, `asset_overrides`, or
`cashflows` sheets. Reads and preflight Google Sheets nodes use `Execute Once`;
row writes must process every prepared row. Preserve finite execution timeouts
and bounded retries.

Repository workflow exports stay inactive so imports are safe. Runtime
publishing is an operator action described in `docs/operations.md`.

## Authentication and secrets

Never commit or log credentials, passwords, MFA values, TOTP secrets, backup
codes, cookies, bearer tokens, Google OAuth material, n8n credential IDs, or raw
private portfolio payloads.

Use the environment variables documented in `.env.example`. The optional bridge
API key protects snapshot routes from other local-network clients. The bridge is
bound to localhost by default and must not be made public without an explicit
security design.

The session store may persist only the verified minimum Clerk restart state:
the session identifier and production `__client` cookie. Bearer JWTs remain
memory-only. The session volume is bridge-only, mode-restricted, excluded from
backups, and cleared when rejected. HTTP routes must never prompt interactively.

Finary authentication material must not enter n8n. Google OAuth material must
not enter the bridge, workflow exports, or repository files.

Fixtures and examples must be synthetic and anonymized. Never capture real data
into the repository before sanitizing it.

## Operational invariants

- The Compose stack owns `finary-bridge`, `schema-server`, and `n8n` on one
  private network; only bridge and n8n bind localhost ports.
- `finary_session_data` and `n8n_data` are separate named volumes.
- The schema server exposes the canonical JSON to n8n without credentials.
- The scheduled workflow runs at 07:30 `Europe/Paris` when published.
- `SUCCESS` and `SUCCESS_WITH_WARNINGS` are valid completed sync states. A later
  `FAILED` row does not replace the newest successful state.
- A state older than 48 hours is operationally stale.
- Google and n8n errors written to telemetry must be sanitized and bounded.
- Back up n8n state and the encryption key separately. Do not routinely use
  `docker compose down -v` and do not back up Finary session state.

## Testing

Normal tests must be credential-free and must not contact Finary, Google, or
public services. Inject fake clients at the FastAPI boundary and use anonymized
fixtures for adapter and normalization tests.

Run the complete local gate from the repository root:

```bash
cd finary-bridge
python -m pytest -m "not live" --ignore=tests/live
ruff check app tests
mypy app
cd ..
python scripts/validate-json.py
docker compose config --quiet
bash scripts/validate-n8n-imports.sh
```

Live tests remain opt-in. They must print structural results only, never values
or secrets, and must be skipped by default in CI. See `docs/development.md`.

Before finishing, also inspect `git diff`, search changed files for secrets or
private data, and check that documentation links resolve.

## Git discipline

- Preserve unrelated work and do not rewrite user changes.
- Prefer one coherent commit per change.
- Do not commit, push, open a pull request, tag, or publish a release unless the
  user explicitly asks.
- Never weaken validation or security controls merely to make a check pass.
- Report files changed, commands and results, assumptions, and remaining
  operational or release blockers.
