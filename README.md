# Finary Portfolio Data Bridge

This repository provides a local, self-hosted pipeline for making normalized
Finary portfolio data available to Google Sheets and ChatGPT:

```text
Finary -> finary-bridge -> n8n -> Google Sheets -> ChatGPT
```

Phases 1 through 10 implement and accept the bridge and inactive operational
pipeline. Phase 11 adds credential-free GitHub Actions quality gates; remote CI
observation remains pending until the change is published. The live
liability investigation could not prove complete coverage, so issue #23 makes
schema `2.0` the canonical workbook and workflow contract. Phase 8 accepts
a narrowly scoped, bridge-only persisted Clerk session after live restart
verification. Private Finary fields remain confined to the adapter and
normalizer. The canonical daily workflow remains inactive pending the separate
production activation gate.

Phase 9's sanitized application acceptance evidence is recorded in
[`docs/end-to-end-acceptance.md`](docs/end-to-end-acceptance.md). Phase 10's
sanitized live-stack migration evidence is recorded in
[`docs/compose-migration.md`](docs/compose-migration.md).

## Prerequisites

- Python 3.12 or newer
- Node.js 22.23.2 for executable n8n Code-node tests
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

Schema `1.0` remains fail-safe and returns `FINARY_FEATURE_UNAVAILABLE` when
liability coverage is incomplete. Schema `2.0` returns valid assets with
explicit coverage and nullable liability-dependent totals:

```bash
curl http://127.0.0.1:8000/v2/snapshot
```

The current live adapter reports `coverage.liabilities = UNAVAILABLE`, an empty
liability list, and null `liabilities_eur`/`net_worth_eur`. It does not publish
zero liabilities or a misleading net worth.

## Run with Docker Compose

Copy the example environment file and set the local secrets and workbook ID:

```bash
cp .env.example .env
docker compose up --build
```

The accepted live stack is now owned by this repository's Compose project. The
bridge and n8n are bound to `127.0.0.1:8000` and `127.0.0.1:5678`. The
canonical schema service is private to the Compose network. n8n data is stored
in `n8n_data`; the sensitive Clerk restart state is isolated in the separate
bridge-only `finary_session_data` named volume. Stop the stack without deleting
either volume with:

```bash
docker compose down
```

## Quality checks

From `finary-bridge` with the virtual environment active:

```bash
python -m pytest -m "not live" --ignore=tests/live
python -m ruff check .
python -m mypy app
```

From the repository root, reproduce the remaining CI contracts with:

```bash
python scripts/validate-json.py
docker compose config --quiet
bash scripts/validate-n8n-imports.sh
```

## Continuous integration

The read-only `CI` GitHub Actions workflow validates pull requests and pushes to
`main` through four stable checks: `tests`, `static-analysis`,
`repository-contracts`, and `n8n-import`. Live Finary/session tests and Google
operations are explicitly excluded. See [`docs/ci.md`](docs/ci.md) for runtime
pins, security boundaries, local reproduction, and failure diagnosis.

Successful CI does not activate scheduling. The production daily workflow
remains inactive until issue #18 is explicitly approved.

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
and a daily 07:30 schedule in `Europe/Paris`. It targets the canonical
schema-2.0 workbook and remains inactive/unpublished until production
activation. The workbook must contain headers matching the canonical JSON. See
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

Phases 1 through 11 are implemented locally. Issue #23 implemented the canonical schema
`2.0` contract, workbook, and inactive workflows. Phase 9 then accepted the
merged end-to-end path with a protected-session restart, sanitized live v2
snapshot, one inactive manual synchronization, workbook integrity checks, and
credential-free lifecycle/recovery tests. It does not enable production
scheduling.
Phase 7 reached
[Outcome B](docs/liability-coverage-investigation.md): neither `finary_uapi`
0.2.3 nor the additional organization-scoped traffic evidence proves a complete
liability collection. The daily production schedule therefore remains disabled.
The canonical v2 bridge publishes truthful asset state with explicit incomplete
coverage while withholding liability-dependent totals.

Phase 8 reached
[Outcome A](docs/finary-authentication-investigation.md). After one explicit
MFA bootstrap, the bridge persists only Clerk's session ID and `__client`
cookie in a protected bridge-only store. Live verification proved that fresh
clients and a separate process can mint new short-lived JWTs without another
MFA code while that upstream session remains valid. TOTP secrets, backup codes,
one-time codes, bearer JWTs, and raw authentication responses remain prohibited.

The post-Phase-6 roadmap uses ordinal titles 07–13; the corresponding GitHub
issue numbers are #13–#19:

1. [Resolve liability coverage and snapshot completeness (#13)](https://github.com/notflorian/finary-chatgpt/issues/13): Outcome B documented; schema `1.0` remains fail-safe.
2. [Implement secure non-interactive Finary authentication (#14)](https://github.com/notflorian/finary-chatgpt/issues/14): Outcome A implemented and restart-verified; periodic human MFA remains necessary after expiry or revocation.
3. [Adopt schema 2.0 explicit liability coverage (#23)](https://github.com/notflorian/finary-chatgpt/issues/23): implemented as the canonical pre-production workflow/workbook contract and live-accepted while inactive.
4. [Complete live snapshot and end-to-end acceptance (#15)](https://github.com/notflorian/finary-chatgpt/issues/15): accepted under schema 2.0; see the [sanitized evidence](docs/end-to-end-acceptance.md).
5. [Migrate the live stack to repository Docker Compose (#16)](https://github.com/notflorian/finary-chatgpt/issues/16): accepted; the repository Compose project now owns all three live services and persistent n8n state.
6. [Add CI quality gates (#17)](https://github.com/notflorian/finary-chatgpt/issues/17): implemented locally; GitHub-hosted observation remains pending publication.
7. [Activate production synchronization safely (#18)](https://github.com/notflorian/finary-chatgpt/issues/18): remains the explicit activation gate after Phase 11 is published and green.
8. [Connect ChatGPT to the validated workbook (#19)](https://github.com/notflorian/finary-chatgpt/issues/19), blocked by #18.

Issue #13 remains an evidence-backed Outcome B and an explicit limitation of
liability/net-worth analysis. Schema 2.0 allows truthful asset synchronization
without weakening that limitation. The
Phase 9 prerequisite investigation confirmed that the organization-scoped
overview and credits surfaces are callable, but every membership returned an
empty credit collection and no representative record or complete-zero contract.
Issue #14 resolves the routine restart-authentication blocker without enabling
the schedule. Schema `2.0` is the inactive canonical path and passed protected
workbook migration and same-day idempotency acceptance.
Persisted Clerk state is allowed only in the minimal protected bridge store;
never persist TOTP secrets, backup codes, one-time MFA codes, or bearer JWTs,
and never interpret empty nested `loans` arrays as zero liabilities. ChatGPT
must never receive Finary credentials or raw private API payloads.

The Google Sheets schema is documented in
[`docs/google-sheets-schema.md`](docs/google-sheets-schema.md). Its canonical,
dependency-free initialization definition is
[`docs/google-sheets-schema.json`](docs/google-sheets-schema.json). The JSON
defines all ten sheet names, ordered headers, types, nullability, ownership,
unique keys, and enum values without calling Google APIs.

The completed migration evidence and promotion decision are documented in
[`docs/schema-v2-migration-plan.md`](docs/schema-v2-migration-plan.md).
The final inactive end-to-end acceptance is documented in
[`docs/end-to-end-acceptance.md`](docs/end-to-end-acceptance.md).

## Security and scope

- Keep `.env` local; it is ignored by Git.
- Never add Finary credentials to Google Sheets, ChatGPT, logs, or commits.
- `GET /health` has no upstream dependencies and never creates a Finary client.
- `GET /v1/snapshot` returns only strict Pydantic models with schema version
  `1.0`, category-aware keys, allowlisted fields, and sanitized errors.
- `GET /v2/snapshot` preserves those asset models and adds strict explicit
  liability coverage with nullable dependent totals.
- Finary credentials are read from `FINARY_EMAIL`, `FINARY_PASSWORD`, and the
  optional `FINARY_MFA_CODE` environment variable.
- The private API surface was verified against `finary_uapi` 0.2.3. The bridge
  uses `curl-cffi` directly because that library's helper persists JWT/cookie
  files and may debug-log complete entity payloads; neither behavior is suitable
  for this service boundary.
- Authentication uses the verified Clerk password flow with TOTP or prepared
  email-code challenges. It persists only the Clerk session ID and `__client`
  cookie in the configured protected store and keeps bearer JWTs in memory.
- Phase 8 inspected the current Finary Clerk configuration, Clerk lifecycle
  documentation, and `finary_uapi` refresh implementation. Live tests verified
  supported refresh across fresh clients and a separate process. See
  [`docs/finary-authentication-investigation.md`](docs/finary-authentication-investigation.md).
- The adapter retrieves holding accounts and the verified asset collections
  for securities, crypto, euro funds, crowdlending, generic assets, precious
  metals, real estate, SCPI, and startups.
- Phase 7 inspected `finary_uapi` 0.2.3 at its exact upstream revision and
  current organization-scoped traffic evidence. A credits category and loan
  status flags exist in the latter evidence, but their completeness, dedicated
  liability shape, identity, lifecycle, and EUR semantics are not proven. See
  [`docs/liability-coverage-investigation.md`](docs/liability-coverage-investigation.md).
- Raw liability results carry an explicit completeness state. Only a verified
  `COMPLETE` source can make an empty collection mean zero; `PARTIAL` and
  `UNAVAILABLE` remain `FINARY_FEATURE_UNAVAILABLE`.
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

To verify protected restart reuse, set an absolute empty `FINARY_SESSION_PATH`
outside the repository and run the separate sanitized diagnostic:

```bash
FINARY_LIVE_SESSION_TEST=1 \
  python -m pytest -m live tests/live/test_finary_session_live.py -vv -s --tb=no
```

The test prompts once, persists no bearer JWT or MFA material, and verifies two
fresh-client refreshes without printing cookie, token, session, identity, or
portfolio values. Manual MFA is required again after session expiry or
revocation.
