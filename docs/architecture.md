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
- Finary session cookies
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
```

The bridge should be reachable by n8n as:

```text
http://finary-bridge:8000
```

The bridge should not expose a public Internet port unless specifically required.

Example conceptual `docker-compose.yml`:

```yaml
services:
  finary-bridge:
    build:
      context: ./finary-bridge
    env_file:
      - .env
    networks:
      - finary-stack

  n8n:
    image: n8nio/n8n:latest
    environment:
      TZ: Europe/Paris
      GENERIC_TIMEZONE: Europe/Paris
    volumes:
      - n8n_data:/home/node/.n8n
    networks:
      - finary-stack
    depends_on:
      - finary-bridge

networks:
  finary-stack:

volumes:
  n8n_data:
```

Exact versions should be pinned before production use.

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

Recommended approach:

- bridge computes normalized component values
- n8n recomputes summary totals as a consistency check

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
- `market_value_eur`

Nullable fields should remain nullable rather than using fake values.

## 6.2 Position

Suggested schema:

```json
{
  "position_key": "finary:12345:asset:67890",
  "source": "finary",
  "source_asset_id": "67890",
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
2026-08-20:finary:12345:asset:67890
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

Percentages should use a clearly documented denominator.

Recommended:

```text
asset class percentage =
asset class market value /
sum of active position market values
```

Do not mix liabilities into asset allocation percentages.

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
equity-main,EQUITY,,75,70,80,Main equity target,TRUE
bond-main,BOND,,25,20,30,Main bond target,TRUE
```

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

Conceptual workflow:

```text
Manual Trigger -----+
                    |
Schedule Trigger ---+
                    |
                    v
Generate run context
                    |
                    v
HTTP GET /v1/snapshot
                    |
                    v
Validate snapshot
                    |
                    v
Load asset_overrides
                    |
                    v
Apply overrides
                    |
                    v
Calculate totals and weights
                    |
                    v
Load current accounts and positions
                    |
                    v
Detect disappeared records
                    |
          +---------+---------+
          |                   |
          v                   v
Upsert accounts       Upsert positions
                              |
                              v
                    Mark missing inactive
                              |
                              v
                    Upsert position history
                              |
                              v
                    Upsert liabilities
                              |
                              v
                    Upsert portfolio_daily
                              |
                              v
                    Append sync_runs SUCCESS
```

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
position_key = finary:12345:asset:67890
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
- recompute totals
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
FINARY_BRIDGE_API_KEY
```

If the private Finary authentication requires interactive MFA or session bootstrap, Codex must adapt the implementation based on observed behavior rather than inventing an unsupported flow.

Prefer reusing a valid session mechanism when supported by the chosen upstream client.

Never expose these values downstream.

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

The first real milestone is not the n8n workflow.

It is:

```text
GET /health
GET /v1/snapshot
```

with a stable normalized snapshot.

Do not build downstream automation around unverified Finary assumptions.

## 33. Recommended Codex execution sequence

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

## 34. Final acceptance checklist

The implementation is ready when all of the following are true:

```text
[ ] docker compose starts successfully
[ ] /health returns 200
[ ] /v1/snapshot returns normalized JSON
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
