# Architecture

## 1. Purpose

This project makes a Finary portfolio available to ChatGPT through a normalized Google Sheets data model.

Target pipeline:

```text
Finary
  |
  v
finary-bridge
  |
  v
n8n
  |
  v
Google Sheets
  |
  v
Google Drive
  |
  v
ChatGPT
```

The architecture intentionally isolates Finary behind `finary-bridge` because Finary does not provide a stable public API contract for this use case.

The downstream model must remain stable even if the private Finary response schema changes.

## 2. Design goals

The system must be:

- local-first
- self-hostable
- idempotent
- auditable
- recoverable
- safe for sensitive financial data
- tolerant of upstream schema changes
- easy for ChatGPT to interpret

The system should optimize for correctness and maintainability rather than real-time updates.

A daily synchronization is sufficient.

## 3. Components

### 3.1 Finary

Finary is the source of portfolio information.

Expected categories may include:

- bank accounts
- PEA
- CTO
- assurance-vie
- cash
- securities
- real estate
- SCPI
- crypto
- liabilities

Exact upstream capabilities depend on the private API and must not be assumed blindly.

### 3.2 finary-bridge

`finary-bridge` is a local FastAPI service.

Responsibilities:

- authenticate against Finary
- retrieve raw Finary data
- translate upstream fields into a stable internal schema
- generate stable identifiers
- normalize amounts to EUR when possible
- validate normalized data
- return versioned JSON
- hide private Finary response shapes from n8n

Non-responsibilities:

- Google Sheets writes
- historical persistence
- portfolio target allocation
- ChatGPT integration
- user-facing investment advice

### 3.3 n8n

n8n orchestrates synchronization.

Responsibilities:

- trigger synchronization
- call the bridge
- validate snapshot consistency
- read manual asset overrides
- apply final classifications
- calculate totals and portfolio weights
- write current-state sheets
- write daily history sheets
- mark disappeared records inactive
- record synchronization runs
- handle workflow failures

### 3.4 Google Sheets

Google Sheets acts as a lightweight analytical datastore.

It is intentionally divided between:

- current state
- historical state
- manually maintained metadata
- synchronization telemetry

### 3.5 ChatGPT

ChatGPT reads the Google Sheet through Google Drive integration.

ChatGPT should not receive:

- Finary password
- Finary session cookies or session identifiers
- private Finary API tokens
- raw authentication payloads

ChatGPT consumes normalized tables only.

## 4. Deployment topology

Recommended local deployment:

```text
Host machine
|
+-- Docker network: finary-stack
    |
    +-- n8n
    |
    +-- finary-bridge
    |
    +-- schema-server
```

The bridge should be reachable by n8n as:

```text
http://finary-bridge:8000
```

The bridge should not expose a public Internet port unless specifically required.

The implemented `docker-compose.yml` pins reviewed image versions and digests:

```yaml
services:
  finary-bridge:
    build:
      context: ./finary-bridge
    env_file:
      - .env
    volumes:
      - finary_session_data:/var/lib/finary-session
    networks:
      - finary-stack

  n8n:
    image: n8nio/n8n:2.35.5@sha256:...
    environment:
      TZ: Europe/Paris
      GENERIC_TIMEZONE: Europe/Paris
    volumes:
      - n8n_data:/home/node/.n8n
    networks:
      - finary-stack
    depends_on:
      - finary-bridge
      - schema-server

  schema-server:
    image: nginx:1.31.4@sha256:...
    volumes:
      - ./docs/google-sheets-schema.json:/usr/share/nginx/html/google-sheets-schema.json:ro
    networks:
      - finary-stack

networks:
  finary-stack:

volumes:
  n8n_data:
```

Only bridge and n8n bind localhost host ports. The schema service remains
private to `finary-stack`.

## 5. Bridge API

## 5.1 GET /health

Purpose:

- container health check
- local diagnostics

Must not call Finary.

Response:

```json
{
  "status": "ok",
  "service": "finary-bridge",
  "version": "0.1.0"
}
```

## 5.2 GET /v1/snapshot

Purpose:

Return one normalized point-in-time portfolio snapshot.

Suggested response:

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-08-20T07:30:12+02:00",
  "reference_currency": "EUR",
  "gross_assets_eur": 402100.42,
  "liabilities_eur": 77520.20,
  "net_worth_eur": 324580.22,
  "accounts": [],
  "positions": [],
  "liabilities": []
}
```

The monetary totals may be calculated by the bridge or n8n, but a single source of truth must be selected and documented.

Implemented approach:

- the bridge computes authoritative normalized totals;
- n8n copies those totals, validates their internal relationships, and derives
  only the known-EUR position analytics defined by the Sheets schema;
- n8n never recalculates gross assets from positions or adds account and
  position values together.

Phase 3 uses non-collection account balances as the sole source for
`gross_assets_eur`. It never adds position values to account balances. An
account is excluded only when the verified upstream `is_collection` field is
exactly `true`; a missing field is treated as a leaf account for compatibility
with the canonical fixture. Every included account balance must have explicit
EUR currency provenance or snapshot normalization fails.

A successful schema `1.0` response has numeric `gross_assets_eur`,
`liabilities_eur`, and `net_worth_eur`. The live adapter reports an explicit
`UNAVAILABLE` raw coverage container; the v1 normalization policy maps it to
`FinaryFeatureUnavailableError`, so `/v1/snapshot` returns
`FINARY_FEATURE_UNAVAILABLE` instead of assuming zero. A known-empty complete
collection remains distinct and may produce `liabilities_eur = 0`.

Phase 3 maps application failures to a stable error envelope. Messages are
fixed and never include raw adapter exception text.

| Error code | HTTP status | Source |
| --- | ---: | --- |
| `FINARY_AUTH_FAILED` | 502 | `FinaryAuthenticationError` |
| `FINARY_TIMEOUT` | 504 | `FinaryUpstreamTimeoutError` |
| `FINARY_MALFORMED_RESPONSE` | 502 | `FinaryMalformedResponseError` |
| `FINARY_UPSTREAM_ERROR` | 502 | `FinaryUpstreamError` or unknown adapter error |
| `FINARY_FEATURE_UNAVAILABLE` | 503 | `FinaryFeatureUnavailableError` |
| `SNAPSHOT_VALIDATION_FAILED` | 502 | normalized contract validation failure |

## 5.3 GET /v2/snapshot

Schema `2.0` reuses the stable account, position, and liability models and adds
`coverage.liabilities` with `COMPLETE`, `PARTIAL`, or `UNAVAILABLE`.
`gross_assets_eur` remains the authoritative account-balance total.

- `COMPLETE` requires finite numeric `liabilities_eur` and `net_worth_eur`, the
  normalized-liability sum, and `net_worth_eur = gross_assets_eur -
  liabilities_eur`.
- `PARTIAL` and `UNAVAILABLE` require null liability and net-worth totals.
- `UNAVAILABLE` cannot claim authoritative liability records.

The current live adapter therefore yields HTTP 200 from `/v2/snapshot` with
valid assets, `coverage.liabilities = UNAVAILABLE`, an empty liability list,
and null liability-dependent totals. Genuine authentication, timeout,
malformed-response, upstream, and normalization failures retain the sanitized
error mapping above. `/v1/snapshot` is unchanged.

## 6. Stable data models

## 6.1 Account

Suggested schema:

```json
{
  "account_key": "finary:account:12345",
  "source": "finary",
  "source_account_id": "12345",
  "name": "PEA",
  "institution": "Example Bank",
  "account_type": "PEA",
  "owner": null,
  "currency": "EUR",
  "market_value_eur": 84320.15,
  "metadata": {}
}
```

Required:

- `account_key`
- `source`
- `source_account_id`
- `name`
- `account_type`

Nullable fields should remain nullable rather than using fake values.
`market_value_eur` is nullable on the model, but every non-collection account
must have a proven EUR value for a successful snapshot total.

## 6.2 Position

Suggested schema:

```json
{
  "position_key": "finary:12345:asset:securities:67890",
  "source": "finary",
  "source_asset_id": "securities:67890",
  "account_key": "finary:account:12345",
  "name": "Example ETF",
  "ticker": null,
  "isin": null,
  "asset_class": "EQUITY",
  "asset_subclass": "WORLD_EQUITY",
  "region": null,
  "quantity": 100.0,
  "unit_price": 100.0,
  "currency": "EUR",
  "fx_to_eur": 1.0,
  "market_value_native": 10000.0,
  "market_value_eur": 10000.0,
  "cost_basis_eur": null,
  "unrealized_pnl_eur": null,
  "unrealized_pnl_pct": null,
  "metadata": {}
}
```

`position_key` must be unique across the portfolio.

Do not use ticker as identifier.

Do not use ISIN alone as identifier because the same instrument may exist in multiple accounts.

Position identities are category-aware because numeric record IDs are not
globally unique across Finary collections:

```text
source_asset_id = {position_kind}:{position_id}
position_key = finary:{account_id}:asset:{position_kind}:{position_id}
```

The authoritative account reference is the top-level
`holdings_account_id`. Nested `account` and `bank_account` objects are ignored.

### 6.2.1 Phase 3 position mappings

Only collections with a non-empty verified fixture have normalization rules.
Non-empty data from another collection fails explicitly until a verified
handler is added.

| Position kind | Name | Ticker/code | ISIN | Market currency | Classification |
| --- | --- | --- | --- | --- | --- |
| `securities` | `security.name` | `security.symbol` | `security.isin` | `security.currency.code` | `OTHER` |
| `cryptos` | `crypto.name` | `crypto.code` | null | unverified | `CRYPTO` |
| `fonds_euro` | top-level `name` | null | null | top-level `currency.code` | `LIFE_INSURANCE_FUND` |
| `generic_assets` | top-level `name` | null | null | top-level `currency.code` | `OTHER` |
| `real_estates` | top-level `name` | null | null | top-level `currency.code` | `REAL_ESTATE` |
| `scpis` | `scpi.name` | null | null | unverified | `SCPI` |

All supported kinds use the record `id`, `holdings_account_id`, `quantity`,
`current_price`, `current_value`, and `buying_value` where present. SCPI uses
top-level `quantity`, falling back to verified `shares` only when quantity is
absent. Real-estate `current_value` is not adjusted again by ownership
percentage.

`market_value_native` uses top-level `current_value`. `market_value_eur` and
`fx_to_eur = 1.0` are populated only when the market-value currency source in
the table is exactly `EUR`. `cost_basis_eur` uses `buying_value` only when its
verified cost currency is EUR. For crypto, `buying_price_currency.code` proves
cost-basis currency only; it does not prove current-value currency. No
speculative FX conversion or `display_*` inference is performed.

The Phase 3 metadata allowlist is empty. Every normalized account, position,
and liability returns `{}` for `metadata`; complete upstream records and nested
private objects are never copied.

## 6.3 Liability

Suggested schema:

```json
{
  "liability_key": "finary:liability:98765",
  "source": "finary",
  "source_liability_id": "98765",
  "name": "Mortgage",
  "liability_type": "MORTGAGE",
  "institution": "Example Bank",
  "outstanding_eur": 77520.20,
  "interest_rate": null,
  "monthly_payment_eur": null,
  "end_date": null,
  "metadata": {}
}
```

The model is implemented, but Phase 7 concluded with Outcome B: no verified
complete liability source. `finary_uapi` 0.2.3 at revision
`be147ce47eb0acb3b8f2b1d2152c551953e775bd` contains no liability reader. Its
documented `loans` CLI command has no dispatch implementation. Independent
organization-scoped traffic evidence exposes a `credits/accounts` category and
portfolio loan-status flags, but does not prove portfolio-wide completeness,
a dedicated non-empty liability schema, identity/deduplication, lifecycle, or
EUR provenance.

`FinaryRawLiabilities` therefore carries explicit `COMPLETE`, `PARTIAL`, or
`UNAVAILABLE` coverage. Only `COMPLETE` can be normalized by schema `1.0`.
An explicitly complete empty collection may produce known zero in deterministic
tests; partial or unavailable empty collections still raise
`FinaryFeatureUnavailableError`. Empty nested `loans` arrays remain ignored and
never prove zero liabilities. The current live v1 endpoint returns the
structured unavailable-feature error before calculating net worth.

The full evidence and implemented schema `2.0` coverage contract are in
[`liability-coverage-investigation.md`](liability-coverage-investigation.md).
The v2 contract adds an explicit liability coverage state and keeps
`liabilities_eur` and `net_worth_eur` null for `PARTIAL` or `UNAVAILABLE`.
It is exposed through `/v2/snapshot`, the canonical Sheets schema, and the
canonical inactive n8n workflow. The older workbook and workflow artifacts were
removed after live validation because this pre-1.0 system was never in
production. `/v1/snapshot` remains temporarily available and fail-safe, but is
not a backward-compatibility promise.

## 6.4 Phase 4 handoff constraints

The Google Sheets schema phase must preserve these Phase 3 semantics:

- `source_asset_id` and `position_key` include the position kind.
- Position `market_value_eur`, `cost_basis_eur`, `currency`, and `fx_to_eur`
  may be null when upstream currency provenance is incomplete.
- A structured snapshot error means no complete snapshot exists; downstream
  code must not replace unavailable liabilities or net worth with zero.
- Account balances are the authoritative gross-assets source. Position values
  are analytical components and must not be added to account totals.
- `metadata` is currently empty by policy and cannot be used as a raw upstream
  escape hatch.

## 7. Google Sheets workbook

Workbook:

```text
Finary Portfolio Data
```

Sheets:

```text
README
accounts_current
positions_current
liabilities_current
positions_history
portfolio_daily
allocation_targets
asset_overrides
cashflows
sync_runs
```

Phase 4 makes [`google-sheets-schema.json`](google-sheets-schema.json) the
canonical ordered header/type/ownership definition and
[`google-sheets-schema.md`](google-sheets-schema.md) the complete data
dictionary. The sections below remain the conceptual overview; the Phase 4
schema is authoritative where it adds nullability and ownership detail.

Unknown numeric values use blank cells, never zero or text placeholders.
Position currency-derived values remain blank when Phase 3 cannot prove EUR
provenance. A structured bridge error produces no portfolio write and cannot
clear or deactivate the last valid state. No sheet contains raw metadata.

## 8. README sheet

Purpose:

Provide a human-readable and ChatGPT-readable data dictionary.

Recommended rows:

```text
reference_currency = EUR
timezone = Europe/Paris
current_state_rule = sheets ending in _current contain the latest known state
history_rule = positions_history contains daily position snapshots
override_rule = asset_overrides takes precedence over automatic classification
net_worth_rule = gross_assets_eur - liabilities_eur
```

Also document every important column.

## 9. accounts_current

One row per account.

Columns:

```text
account_key
source
source_account_id
name
institution
account_type
owner
currency
market_value_eur
last_seen_at
last_seen_run_id
is_active
```

Unique key:

```text
account_key
```

Update behavior:

- upsert on `account_key`
- missing previously active account -> `is_active = FALSE`

Never delete rows automatically.

## 10. positions_current

One row per account-position combination.

Columns:

```text
position_key
source
source_asset_id
account_key
account_name
account_type
institution
name
ticker
isin
asset_class
asset_subclass
region
quantity
unit_price
currency
fx_to_eur
market_value_native
market_value_eur
cost_basis_eur
unrealized_pnl_eur
unrealized_pnl_pct
weight_portfolio
last_seen_at
last_seen_run_id
is_active
```

Unique key:

```text
position_key
```

Only rows where:

```text
is_active = TRUE
```

represent the current portfolio.

## 11. liabilities_current

Columns:

```text
liability_key
source
source_liability_id
name
liability_type
institution
outstanding_eur
interest_rate
monthly_payment_eur
end_date
last_seen_at
last_seen_run_id
is_active
```

Unique key:

```text
liability_key
```

The sheet is forward-compatible and may remain empty while Phase 3 liability
coverage is unavailable. Empty does not prove zero liabilities. An unavailable
snapshot must not create a synthetic row, clear prior valid rows, or mark them
inactive.

## 12. positions_history

One row per day and position.

Columns:

```text
history_key
snapshot_date
generated_at
position_key
account_key
source_asset_id
name
ticker
isin
asset_class
asset_subclass
quantity
unit_price
currency
fx_to_eur
market_value_eur
cost_basis_eur
```

Unique key:

```text
history_key
```

Construct:

```text
{snapshot_date}:{position_key}
```

Example:

```text
2026-08-20:finary:12345:asset:securities:67890
```

Behavior:

- rerun same day -> update existing row
- next day -> append a new row
- historical rows are never deleted

## 13. portfolio_daily

One row per calendar day.

Columns:

```text
snapshot_date
generated_at
gross_assets_eur
liabilities_eur
net_worth_eur
financial_assets_eur
equity_eur
bond_eur
cash_eur
real_estate_eur
scpi_eur
private_equity_eur
crypto_eur
commodity_eur
life_insurance_fund_eur
other_eur
equity_pct
bond_pct
cash_pct
real_estate_pct
scpi_pct
private_equity_pct
crypto_pct
commodity_pct
life_insurance_fund_pct
other_pct
pea_eur
cto_eur
life_insurance_eur
cash_accounts_eur
run_id
```

Unique key:

```text
snapshot_date
```

Under schema `1.0`, only a complete successful snapshot writes this sheet.
Under schema `2.0`, every valid asset snapshot writes explicit
`liability_coverage`; incomplete coverage keeps liability and net-worth cells
blank and never implies zero. `gross_assets_eur` remains the authoritative
account-balance total and is never calculated by adding account and position
values.

Percentages should use a clearly documented denominator.

Recommended:

```text
asset class percentage =
asset class market value /
sum of active position market values with known EUR values
```

Do not mix liabilities into asset allocation percentages.
If any active position lacks a verified EUR value, these percentages describe
the known-EUR subset and must not be presented as full gross-portfolio coverage.

## 14. allocation_targets

Manual sheet.

Suggested columns:

```text
target_key
asset_class
asset_subclass
target_pct
min_pct
max_pct
notes
enabled
```

Example:

```text
equity-main,EQUITY,,0.75,0.70,0.80,Main equity target,TRUE
bond-main,BOND,,0.25,0.20,0.30,Main bond target,TRUE
```

Percentages are stored as decimal fractions: `0.75` means 75%.

This sheet is not overwritten by n8n.

## 15. asset_overrides

Manual sheet.

Purpose:

Correct or enrich automatic classification.

Columns:

```text
override_key
source_asset_id
isin
ticker
name_match
custom_asset_class
custom_asset_subclass
custom_region
notes
enabled
```

Matching precedence should be deterministic.

Recommended order:

1. source_asset_id
2. ISIN
3. ticker
4. exact normalized name match

Avoid fuzzy matching in the first implementation.

If several enabled overrides match the same position at the same precedence, treat it as a validation error.

## 16. cashflows

Manual or future automated sheet.

Purpose:

Distinguish investment performance from external contributions and withdrawals.

Columns:

```text
cashflow_key
date
account_key
amount_eur
type
notes
source
```

Allowed `type` values:

```text
CONTRIBUTION
WITHDRAWAL
DIVIDEND
INTEREST
FEE
TAX
TRANSFER
```

Do not assume Finary provides sufficient transaction-level information.

This sheet may initially be maintained manually.

## 17. sync_runs

One row per n8n execution.

Columns:

```text
run_id
started_at
completed_at
status
accounts_count
positions_count
liabilities_count
gross_assets_eur
liabilities_eur
net_worth_eur
previous_net_worth_eur
net_worth_change_pct
duration_ms
bridge_version
schema_version
warning_count
error_code
error_message
```

Suggested statuses:

```text
SUCCESS
SUCCESS_WITH_WARNINGS
FAILED
```

## 18. Asset classification

Normalized top-level values:

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

Possible subclasses:

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

The bridge may generate an initial classification.

n8n must apply `asset_overrides` afterwards.

## 19. n8n main workflow

Name:

```text
Finary - Daily Sync
```

Triggers:

```text
Manual Trigger
Schedule Trigger
```

Schedule:

```text
07:30
Europe/Paris
daily
```

Implemented workflow (`n8n/workflows/finary-daily-sync.json`):

```text
Manual Trigger -----+
                    |
Schedule Trigger ---+
                    |
                    v
Generate run context
                    |
                    v
HTTP GET /v2/snapshot
                    |
                    v
Validate snapshot
                    |
                    v
Load canonical schema and validate workbook headers
                    |
                    v
Load asset_overrides and current state
                    |
                    v
Apply overrides
                    |
                    v
Calculate totals and weights
                    |
                    v
Detect disappeared records
                    |
Build and validate every target row
                    |
                    v
Upsert accounts -> positions -> liabilities -> history -> daily
                    |
                    v
Record terminal sync_runs telemetry
```

Every Google Sheets append-or-update operation uses the canonical Phase 4
unique key. Read-only header probes and in-memory row validation finish before
the first portfolio write. Structured bridge errors branch only to sanitized
failed telemetry and cannot reach current, history, or daily writes. Operational
setup is documented in `docs/n8n-daily-sync.md`.

## 20. Synchronization transaction strategy

Google Sheets does not provide traditional database transactions.

Therefore the workflow must reduce the risk of partial corruption.

Recommended sequence:

1. fetch snapshot
2. validate everything in memory
3. calculate all derived values
4. only then start writes
5. write current-state rows
6. write history
7. write daily summary
8. write successful run telemetry last

If validation fails before step 4:

- do not modify portfolio sheets
- write only a failed `sync_runs` record where possible

If a write fails mid-run:

- mark run failed
- preserve previous rows
- next idempotent rerun should repair the state

Never clear an entire sheet before rewriting it.

## 21. Missing position handling

Example:

Previous current state:

```text
position_key = finary:12345:asset:securities:67890
is_active = TRUE
last_seen_run_id = run-A
```

New snapshot does not contain the position.

After synchronization:

```text
is_active = FALSE
last_seen_run_id = run-A
```

Optionally add:

```text
inactive_since
```

in a later schema version.

Do not set market value to zero unless that is explicitly returned by Finary.

Do not delete historical rows.

## 22. Validation

Bridge-level validation:

- required IDs
- unique keys
- valid numeric values
- valid timestamps
- valid currency code
- account references
- non-negative liabilities

n8n-level validation:

- compare counts with previous successful run
- detect unexpected empty snapshot
- verify authoritative totals without recalculating gross assets from positions
- check portfolio weight sum
- detect duplicate overrides
- check day-over-day net-worth movement

Suggested warnings:

```text
net worth change > 20%
positions count change > 30%
accounts count change > 30%
```

These thresholds should be configurable.

Warnings do not automatically imply failure.

## 23. Error handling workflow

Name:

```text
Finary - Error Handler
```

Trigger:

```text
Error Trigger
```

Responsibilities:

- capture workflow failure
- produce concise error metadata
- append failed `sync_runs` row if possible
- optionally send an email notification

Never include credentials or raw authentication responses in notifications.

Suggested notification:

```text
Finary synchronization failed

Run: 20260821-073000
Step: Fetch snapshot
Error code: FINARY_AUTH_FAILED

Last successful synchronization:
2026-08-20 07:30 Europe/Paris
```

## 24. Authentication

Bridge environment variables:

```text
FINARY_EMAIL
FINARY_PASSWORD
FINARY_MFA_CODE
FINARY_SESSION_PATH
FINARY_BRIDGE_API_KEY
```

Never expose these values downstream.

Phase 8 concludes with Outcome A: the normal Clerk session-token refresh model
is accepted through a narrow protected persistence boundary. The bridge stores
only the current Clerk session ID and production `__client` cookie value. It
uses those values with `POST /v1/client/sessions/{session_id}/tokens` to mint a
new short-lived JWT; bearer JWTs remain in memory. Live verification proved
reuse across fresh clients and a separate process without another MFA code.

The adapter starts password sign-in and completes a challenge only from an
explicit one-time `FINARY_MFA_CODE` or injected interactive provider. HTTP
routes never prompt. FastAPI reuses one process-local client, whose lock avoids
duplicate refresh/bootstrap flows and whose JWT is refreshed after 45 seconds.
On restart, the client loads the protected session store. Definitive Clerk
rejection clears it and returns sanitized `FINARY_AUTH_FAILED`; expiry or
revocation therefore requires a new explicit MFA bootstrap.

Compose mounts `finary_session_data` only at `/var/lib/finary-session` in the
bridge. Versioned JSON is written atomically under owner-only directory/file
permissions. The store is not mounted into n8n or `schema-server`, is not
backed up, and never contains TOTP secrets, backup codes, one-time codes,
passwords, bearer JWTs, browser profiles, or raw authentication responses.
`/health` neither creates the dependency nor reads the session file.

Authentication success and snapshot completeness are separate. After a manual
authentication succeeds, the Phase 7 liability decision still causes schema
`1.0` to return `FINARY_FEATURE_UNAVAILABLE`. See
[`finary-authentication-investigation.md`](finary-authentication-investigation.md)
for the upstream evidence, threat model, lifecycle, and revocation procedure.

## 25. Google authentication

n8n should authenticate to Google Sheets through an n8n credential.

Do not store Google OAuth tokens in repository files.

Keep the workbook private unless deliberately shared.

ChatGPT accesses the workbook through the user's Google Drive connection, independently from n8n's Google credentials.

## 26. ChatGPT usage model

The Google Sheet is designed so ChatGPT can answer questions such as:

```text
Analyze positions_current where is_active = TRUE.
Show the current allocation by asset class.
```

```text
Compare positions_current with allocation_targets.
Calculate the allocation drift.
```

```text
Using portfolio_daily, describe how my portfolio changed since January 1.
```

```text
Using positions_history, identify which positions contributed most to changes in portfolio value.
```

```text
Given a new contribution, show how it could be allocated to reduce drift without selling.
```

The workbook README should make clear that `asset_overrides` is authoritative for final classification.

## 27. Performance versus contributions

A valuation history alone cannot distinguish:

```text
market performance
```

from:

```text
external contributions or withdrawals
```

Therefore proper personal-return calculations require `cashflows`.

Once cashflows are complete enough, the system may calculate:

- money-weighted return
- XIRR
- contribution-adjusted performance
- performance by account
- performance by asset class

Do not calculate these metrics from valuation snapshots alone and label them as investment performance.

## 28. Data retention

Recommended:

- keep all `positions_history`
- keep all `portfolio_daily`
- keep all `sync_runs`
- keep inactive current-state rows
- do not automatically purge data

Expected size remains manageable for a typical personal portfolio.

Example:

```text
50 positions x 365 days = 18,250 position-history rows per year
```

This is acceptable for the intended Google Sheets use case.

## 29. Versioning

The bridge response includes:

```text
schema_version
```

Start with:

```text
1.0
```

Breaking downstream model changes require a new major schema version.

Finary upstream schema changes do not require a downstream schema version change if the bridge can adapt internally.

## 30. Operational schedule

Recommended:

```text
07:30 Europe/Paris every day
```

Also keep a Manual Trigger for:

- initial setup
- debugging
- recovery
- immediate refresh

Do not poll Finary every hour unless a future requirement justifies it.

The production schedule remains inactive while the live bridge returns
`FINARY_FEATURE_UNAVAILABLE` for unverified liability coverage. Manual failures
must not overwrite the previous valid current state.

### Phase 6 operational boundary

The local Compose stack includes digest-pinned n8n 2.35.5 with a persistent
`n8n_data` volume and a private nginx service exposing only the canonical schema
inside the Docker network. Bridge and n8n host ports bind to localhost.

All Google Sheets nodes retry at most three times with the fixed five-second
delay supported by the pinned n8n runtime. The daily workflow times out after
300 seconds and the error workflow after 120 seconds. Read nodes execute once
to prevent request amplification; write nodes process every selected row.

`Finary - Error Handler` is linked after import because n8n remaps workflow IDs.
It handles uncaught failures, classifies them into stable operational codes, and
upserts a sanitized `FAILED` row only in `sync_runs`. Existing terminal rows are
never overwritten. Last success means the newest valid `completed_at` among
`SUCCESS` and `SUCCESS_WITH_WARNINGS`; later failures do not replace it. See
`docs/operations.md` for backup, restore, MFA restart, rotation, quota, upgrade,
and recovery procedures.

## 31. Recovery scenarios

### Finary authentication failure

Expected behavior:

- bridge returns structured error
- no portfolio sheets are modified
- failed run is recorded
- previous valid state remains readable

### Empty malformed snapshot

Expected behavior:

- validation fails
- no current portfolio rows are deactivated
- previous valid state remains untouched

This is critical.

Never interpret an invalid empty snapshot as "all assets were sold".

### Google Sheets temporary failure

Expected behavior:

- workflow fails
- previous written rows remain
- rerunning the same snapshot repairs missing writes without duplicates

### Upstream Finary schema change

Expected behavior:

- tests or live smoke test fail
- modify bridge adapter
- preserve downstream schema
- n8n and Google Sheets remain unchanged

## 32. First implementation milestone

The first real milestone was not the n8n workflow.

It is:

```text
GET /health
GET /v1/snapshot
GET /v2/snapshot
```

with a stable normalized snapshot.

Do not build downstream automation around unverified Finary assumptions.

## 33. Implemented phase sequence and next gates

Phases 1 through 8 and the canonical schema `2.0` implementation in issue #23
are implemented. The prompts below retain the first six
implementation phases as historical incremental delivery context, not as
pending work. Phases 7 and 8 are recorded in the roadmap table and their
investigation documents.

Prompt 1:

```text
Read AGENTS.md and docs/architecture.md.
Implement Phase 1 only.
Do not implement Finary integration yet.
Run tests and linting and summarize the result.
```

Prompt 2:

```text
Implement Phase 2 only.
Create an isolated Finary client adapter.
Do not change the downstream API contract.
Add fixture-based tests for the upstream responses you support.
```

Prompt 3:

```text
Implement Phase 3 only.
Expose GET /v1/snapshot using the stable normalized models.
Add validation and structured errors.
Run the complete test suite.
```

Prompt 4:

```text
Implement Phase 4 only.
Create docs/google-sheets-schema.md and any safe initialization helpers.
Do not create the n8n workflow yet.
```

Prompt 5:

```text
Implement Phase 5 only.
Create an importable n8n workflow for idempotent synchronization to Google Sheets.
Follow the unique-key and history rules exactly.
```

Prompt 6:

```text
Implement Phase 6 only.
Add failure handling, diagnostics, operational documentation and recovery procedures.
```

The approved post-Phase-6 roadmap uses ordinal titles 07–13. GitHub issue
numbers are global across issues and pull requests, so they map to #13–#19:

| Order | GitHub issue | Milestone | Dependency |
| --- | --- | --- | --- |
| 07 | [#13](https://github.com/notflorian/finary-chatgpt/issues/13) | Outcome B: no verified complete liability source; versioned alternative documented | Investigation complete; schema `1.0` blocker remains |
| 08 | [#14](https://github.com/notflorian/finary-chatgpt/issues/14) | Outcome A: protected Clerk session persistence | Restart reuse live-verified; periodic MFA remains after expiry/revocation |
| v2 migration | [#23](https://github.com/notflorian/finary-chatgpt/issues/23) | Explicit liability coverage API, canonical Sheets schema, and inactive workflows | Protected workbook migration and same-day acceptance passed |
| 09 | [#15](https://github.com/notflorian/finary-chatgpt/issues/15) | Complete live snapshot and inactive end-to-end acceptance | Reassess under the accepted schema-2.0 incomplete-coverage criteria |
| 10 | [#16](https://github.com/notflorian/finary-chatgpt/issues/16) | Migrate the live stack to repository Compose | Before activation |
| 11 | [#17](https://github.com/notflorian/finary-chatgpt/issues/17) | Add CI quality gates | Before activation |
| 12 | [#18](https://github.com/notflorian/finary-chatgpt/issues/18) | Activate production synchronization safely | #15, #16, #17 |
| 13 | [#19](https://github.com/notflorian/finary-chatgpt/issues/19) | Connect ChatGPT to the validated workbook | #18 |

Issue #13 produced the explicit versioned completeness design because no
complete source could be proven. Issue #23 implements that design: the
temporarily retained `/v1/snapshot` route remains fail-safe, while
`/v2/snapshot` and the canonical unsuffixed Sheets/workflow artifacts
synchronize truthful asset state
under explicit incomplete coverage without claiming net worth or changing
last-known complete liabilities. The pre-production v1 workbook/workflow
artifacts were removed after protected live migration and same-day idempotency
acceptance. Issue #14 verified routine restart session reuse without persisting
MFA material or bearer JWTs. Production remains gated on inactive end-to-end,
Compose/CI readiness, and activation issues; the daily schedule remains disabled.

## 34. Final acceptance checklist

The implementation is ready when all of the following are true:

```text
[ ] docker compose starts successfully
[ ] /health returns 200
[ ] /v2/snapshot returns normalized JSON with explicit liability coverage
[ ] no Finary secret appears in logs
[ ] no raw Finary payload reaches n8n
[ ] account keys are stable
[ ] position keys are stable
[ ] current-state writes are idempotent
[ ] daily history writes are idempotent
[ ] missing positions become inactive
[ ] invalid empty snapshots cannot deactivate the portfolio
[ ] portfolio_daily contains one row per day
[ ] asset_overrides is applied deterministically
[ ] sync_runs records success and failure
[ ] same-day rerun creates no duplicates
[ ] next-day run creates historical rows
[ ] Google Sheet remains private
[ ] ChatGPT can read the workbook through Google Drive
[ ] upstream schema changes can be fixed only in the bridge
```
