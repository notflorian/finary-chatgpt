# Architecture

## Purpose

Finary Portfolio Data is a local integration boundary between Finary's private
API and downstream analysis tools. It converts unstable upstream responses into
a stable versioned API, then synchronizes validated data into a Google workbook
that ChatGPT can read.

```text
                         local Docker Compose network
                  +-------------------------------------+
                  |                                     |
Finary <----------+ finary-bridge <- HTTP <- n8n        |
                  |                         |            |
                  | schema-server ----------+            |
                  +-------------------------|------------+
                                            v
                                      Google Sheets
                                            |
                                            v
                                    ChatGPT Project
```

The Compose project runs three services:

- `finary-bridge`: FastAPI application and the only Finary-aware component;
- `schema-server`: credential-free internal delivery of the canonical workbook
  schema;
- `n8n`: scheduler, validation layer, Google Sheets synchronization, and
  operational telemetry.

The bridge and n8n bind to localhost. The schema server has no host port.

## Trust boundaries

### Finary boundary

Finary uses a private, unsupported API and must be treated as unstable. All
endpoint knowledge, Clerk authentication, raw response parsing, and upstream
exception translation are isolated in the bridge adapter. Downstream modules do
not import Finary client packages or inspect private payloads.

The adapter returns bridge-owned raw entities. The normalizer then extracts only
verified fields through category-specific handlers and constructs strict
Pydantic models. Raw dictionaries and private nested objects are not exposed in
API metadata.

### Automation boundary

n8n sees only the normalized bridge contract and the canonical workbook schema.
It does not receive Finary credentials, session cookies, or bearer tokens. The
optional `FINARY_BRIDGE_API_KEY` protects snapshot calls from other local
clients.

n8n owns Google OAuth credentials. Credential bindings are runtime-only and are
not present in exported workflow JSON.

### Consumer boundary

Google Sheets contains normalized portfolio state, user-managed analytical
inputs, and sanitized synchronization telemetry. It does not contain Finary or
n8n credentials, raw API responses, or generic metadata blobs.

ChatGPT reads the private workbook through a Project Google Drive source. The
Project receives the workbook semantics as a separate knowledge file, but it
never connects to the bridge or Finary directly.

## Bridge layers

```text
FastAPI routes (main.py)
        |
snapshot orchestration (services/snapshot_service.py)
        |
pure normalization (normalizer.py) ---- stable models (models.py)
        |
Finary adapter (finary_client.py) ---- protected session store
```

- `main.py` handles dependency injection, route declarations, and sanitized
  HTTP errors.
- `snapshot_service.py` authenticates, retrieves each entity collection once,
  validates references, calculates authoritative totals, and builds a snapshot.
- `normalizer.py` owns stable IDs, category-specific extraction, currency
  provenance, and conservative classification.
- `finary_client.py` and `finary_session_store.py` own all private upstream and
  Clerk behavior.

Normal endpoint tests inject deterministic fake clients. `GET /health` does not
instantiate the Finary client or inspect session state.

## API contracts

### `GET /health`

Returns HTTP 200 without contacting Finary:

```json
{
  "status": "ok",
  "service": "finary-bridge",
  "version": "1.0.0"
}
```

### `GET /v2/snapshot`

This is the canonical downstream API. Its top-level schema is:

```json
{
  "schema_version": "2.0",
  "generated_at": "2026-08-24T07:30:12+02:00",
  "reference_currency": "EUR",
  "coverage": {"liabilities": "UNAVAILABLE"},
  "gross_assets_eur": 12345.67,
  "liabilities_eur": null,
  "net_worth_eur": null,
  "accounts": [],
  "positions": [],
  "liabilities": []
}
```

The entity shapes are defined by the strict `Account`, `Position`, and
`Liability` Pydantic models. Unknown optional fields are JSON `null`; extra
fields, non-finite numbers, duplicate keys, and broken position-account
references are rejected.

`coverage.liabilities` has three values:

- `COMPLETE`: liability records and totals are complete; `liabilities_eur` and
  `net_worth_eur` are numeric;
- `PARTIAL`: some liability state is known but completeness is not established;
- `UNAVAILABLE`: no callable, complete liability representation is available.

For `PARTIAL` and `UNAVAILABLE`, liability-dependent totals are null. Empty
liability arrays never imply zero debt.

### `GET /v1/snapshot`

The legacy schema `1.0` route remains available for clients that require a
complete snapshot. It has no coverage field and requires numeric liability and
net-worth totals. It therefore returns a structured unavailable-feature error
when complete liability coverage cannot be established. New consumers must use
`/v2/snapshot`.

### Errors

All application failures use:

```json
{
  "error": {
    "code": "FINARY_AUTH_FAILED",
    "message": "Unable to authenticate with Finary",
    "retryable": false
  }
}
```

Stable error codes include `FINARY_AUTH_FAILED`, `FINARY_TIMEOUT`,
`FINARY_MALFORMED_RESPONSE`, `FINARY_FEATURE_UNAVAILABLE`,
`FINARY_UPSTREAM_ERROR`, and `SNAPSHOT_VALIDATION_FAILED`. Raw upstream messages
and exception chains are never returned.

When `FINARY_BRIDGE_API_KEY` is non-empty, both snapshot routes require an exact
`X-API-Key` match before the Finary client is constructed. Missing or invalid
keys return HTTP 401 with `BRIDGE_AUTH_FAILED`; `/health` remains unauthenticated.

## Identity and normalization

All upstream IDs are canonical strings. A position ID is only unique within its
Finary collection, so every asset identity includes the position kind:

```text
account_key     = finary:account:{account_id}
source_asset_id = {position_kind}:{asset_id}
position_key    = finary:{account_id}:asset:{position_kind}:{asset_id}
```

Positions link to accounts through `holdings_account_id`. Nested `account` and
`bank_account` objects are not authoritative. Dedicated position collections
are the only position source; nested account assets are ignored to prevent
double counting.

Explicit handlers support the structurally verified collections: securities,
cryptos, fonds euro, generic assets, real estate, and SCPIs. Empty or
unverified collections are not assigned speculative schemas. Asset
classification is conservative; uncertain securities and generic assets remain
`OTHER`. User-managed `asset_overrides` can apply deterministic corrections in
n8n.

The downstream metadata allowlist is empty. Useful stable fields must be added
to the versioned models and workbook schema rather than copied into a raw
metadata column.

## Money and coverage

An EUR field is populated only when the corresponding amount has verified EUR
currency provenance or a verified conversion. `display_*` fields are never
treated as proof of EUR. Normalization does not perform speculative FX
conversion.

Non-collection account balances with verified EUR provenance are the sole
source of `gross_assets_eur`. Position values provide analytical detail and are
never added to account balances. If the authoritative total cannot be proved,
snapshot construction fails rather than producing a partial total.

Position allocation totals and weights use only active positions with known EUR
values. They describe the known-EUR position subset and may not reconcile to
gross assets. The workflow records a partial-coverage warning when appropriate.

## Authentication and session lifecycle

The adapter implements Clerk password authentication followed by the supported
TOTP or email-code challenge. An explicit interactive command bootstraps the
session; HTTP requests never prompt.

The protected file store persists only:

- the Clerk session identifier;
- the production `__client` cookie needed to refresh that session.

Access and refresh bearer JWTs remain in memory. The session file uses mode
`0600`, its directory is bridge-only, and rejected state is cleared. The
`finary_session_data` volume is separate from `n8n_data` and is intentionally
excluded from backups. Session expiry or revocation requires another human MFA
bootstrap.

Before every entity GET, including each position collection, the adapter checks
access-token age against its configured refresh interval using a monotonic
clock. An aging token is renewed non-interactively. An entity HTTP 401 permits
at most one recovery renewal and one replay of that GET; it does not establish
that the token expired. HTTP 403 is not replayed. Previously completed
collections are not fetched again, and any unrecovered failure aborts the
snapshot with the existing sanitized error contract.

The process-scoped authentication lock serializes renewal and individual entity
GETs so the transport, cookies, authorization header, and freshness metadata
remain coherent during HTTP session replacement. This trades concurrent network
reads for a small synchronization boundary; it does not lock the entire
snapshot. Recovery tracks the token generation and reuses a newer generation
if another caller has already renewed it. A repeated 401 disables only the
rejected access generation; entity rejection does not erase renewable state.
Refresh endpoint rejection clears stored state, while transient or malformed
refresh failures preserve it but leave the adapter unauthenticated. Entity
renewal never replays password sign-in or invokes MFA when renewable state is
missing. Bearer tokens remain memory-only.

## Synchronization topology

The daily workflow supports manual execution and a 07:30 `Europe/Paris`
schedule. It:

1. resolves one opaque `run_id` from n8n's persisted execution ID and loads
   workbook schema `2.1` from the internal schema server;
2. requests `/v2/snapshot`;
3. validates schema, entities, keys, headers, and safety gates;
4. reads and applies exact-match asset overrides;
5. prepares all rows before any portfolio write;
6. upserts current accounts and positions;
7. updates liability state only for `COMPLETE` coverage;
8. upserts same-day position history with `run_id` membership and the daily summary;
9. writes one terminal `sync_runs` row.

Current-state rows that disappear become inactive rather than being deleted.
History is append-retained across dates and idempotently replaced for the same
date and position key. Consumers accept history only when its run membership
and count match the terminal successful run and daily row. The success marker
is written last; partial Google Sheets writes can invalidate the prior same-day
state, but the mismatch is detectable and a retry repairs deterministic keys.
Manual sheets are never synchronization-owned.

Native node retries stay inside the same n8n execution and retain its identity.
A saved-data execution retry receives a new n8n execution ID but can retain
earlier node output, so the workflow checks identity again immediately before
publishing success. A stale saved identity cannot create a successful terminal
marker; recovery then requires a full new execution, except when only the final
terminal Sheets write itself is being retried after all required writes passed.

Structured bridge failures stop before portfolio writes and may record sanitized
failed telemetry. The linked error workflow derives correlation from the
originating failed n8n execution supplied by the Error Trigger, never from the
error workflow's own execution or wall-clock time. Both workflows use finite
timeouts, and Sheets operations use bounded retries. Read nodes execute once to
prevent quota amplification.

## Versioning

Application release version and data schema version are independent:

- bridge application: `1.0.0`;
- normalized API schema: `2.0`;
- workbook schema: `2.1`;
- canonical route: `/v2/snapshot`.

A patch or minor application release may leave API schema `2.0` unchanged.
Workbook schema `2.1` adds nullable historical run membership without changing
the stable snapshot API. A breaking downstream API contract change requires a
new API major version and coordinated models, workflows, schema, tests, and
consumer documentation.

## Deliberate limitations

- Finary provides no supported public API contract for this use case.
- Liability coverage is not guaranteed complete by the verified upstream
  surface.
- No speculative FX conversion is performed.
- The system is single-user, local-first, and not hardened for public network
  exposure.
- It does not calculate investment performance, ingest bank transactions,
  recommend trades, or execute trades.
