# Google Sheets schema

## 1. Scope and canonical definition

The workbook is named **Finary Portfolio Data**. It is the normalized boundary
between the Phase 3 bridge contract and the future Phase 5 n8n workflow.

[`google-sheets-schema.json`](google-sheets-schema.json) is the canonical,
machine-readable initialization definition. It contains ordered headers, types,
nullability, ownership, unique keys, enums, and update/deletion policies. It is
data only: it has no Google dependency, credentials, network calls, workbook
creation, or synchronization logic.

This phase defines ten sheets:

1. `README`
2. `accounts_current`
3. `positions_current`
4. `liabilities_current`
5. `positions_history`
6. `portfolio_daily`
7. `allocation_targets`
8. `asset_overrides`
9. `cashflows`
10. `sync_runs`

No sheet contains a raw Finary payload or generic metadata column. The Phase 3
metadata allowlist is empty.

## 2. Type, ownership, and null conventions

| Type | Sheets representation |
| --- | --- |
| `STRING` | Plain text. Identifier strings must not be converted to numbers. |
| `NUMBER` | A finite numeric cell, not formatted text. |
| `BOOLEAN` | `TRUE` or `FALSE` only. Never `yes/no` or `1/0`. |
| `DATE` | `YYYY-MM-DD`, interpreted as a Europe/Paris business date. |
| `DATETIME` | ISO 8601 with an explicit offset, for example `2026-08-20T07:30:12+02:00`. |
| `ENUM` | One exact value from the documented enum. |

Each column has one writer classification:

- **automated**: copied from a successful `GET /v1/snapshot` response or
  initialized from the canonical schema;
- **manual**: maintained by the user and never overwritten by portfolio sync;
- **derived**: calculated or joined by the future Phase 5 workflow.

Nullability is independent of ownership. A nullable value is stored as a
completely blank cell. Never write `N/A`, `unknown`, `null`, or `0` as a null
placeholder. Zero is a known numeric value and is materially different from an
unknown value.

Percentages use decimal fractions: `0.75` means 75%. Sheets may format the cell
as `75%`, but its stored numeric value remains `0.75`.

## 3. Contract-wide safety rules

- Preserve `account_key = finary:account:{account_id}`.
- Preserve `source_asset_id = {position_kind}:{asset_id}`.
- Preserve
  `position_key = finary:{account_id}:asset:{position_kind}:{asset_id}`.
- Never key a record by a numeric asset ID, ticker, ISIN, or name alone.
- Never infer EUR from a `display_*` field. Phase 3 does not expose those fields.
- Copy a nullable Phase 3 EUR value to a blank cell; do not convert it to zero.
- A structured bridge error is not a snapshot. It must not update, deactivate,
  or clear portfolio state or history. Phase 5 may append failed telemetry only.
- Account balances and `PortfolioSnapshot.gross_assets_eur` are authoritative
  for gross assets. Position values are analytical components and must never be
  added to account balances.
- Empty liability coverage is meaningful only when Phase 3 returns a successful
  complete snapshot. `FINARY_FEATURE_UNAVAILABLE` does not mean zero liabilities.
- Current-state rows are retained and marked inactive when absent from a later
  complete snapshot. They are never automatically deleted.
- Historical and telemetry rows are retained.

## 4. `README`

Purpose: provide a human-readable and ChatGPT-readable data dictionary.
Ownership: schema-initialized automated content. Portfolio sync must not rewrite
it. Unique key: `key`. Rows are never automatically deleted.

| Column | Type | Nullable | Owner | Source / meaning |
| --- | --- | --- | --- | --- |
| `key` | STRING | No | automated | Stable dictionary entry key. |
| `value` | STRING | No | automated | Human-readable rule or value. |
| `description` | STRING | No | automated | Interpretation guidance. |

Required initialized entries include:

| key | value |
| --- | --- |
| `reference_currency` | `EUR` |
| `timezone` | `Europe/Paris` |
| `current_state_rule` | `_current sheets contain the latest known valid state, including retained inactive rows` |
| `history_rule` | `positions_history contains daily position snapshots` |
| `override_rule` | `asset_overrides is authoritative over automatic classification` |
| `null_rule` | `blank means unknown or unavailable; blank never means zero` |
| `eur_rule` | `position EUR fields exist only with verified EUR provenance` |
| `gross_assets_rule` | `account balances are authoritative; never add position values to account balances` |
| `failed_snapshot_rule` | `an incomplete or failed snapshot must not overwrite the last valid state` |
| `liability_rule` | `unavailable liability coverage is not zero liabilities` |
| `allocation_rule` | `allocation percentages exclude liabilities and use only known-EUR active positions` |

Synthetic example: `timezone | Europe/Paris | Business dates and schedules use Europe/Paris.`

## 5. `accounts_current`

Purpose: one row per normalized account in the latest known valid state.
Ownership: automated snapshot fields plus derived synchronization fields.
Unique key: `account_key`.

Update: upsert by `account_key` only after complete validation. A previously
active account missing from a later complete snapshot becomes `is_active =
FALSE`; retain its previous values and `last_seen_*`. Never delete rows and
never use a display name as an identifier.

| Column | Type | Nullable | Owner | Phase 3 source / derivation |
| --- | --- | --- | --- | --- |
| `account_key` | STRING | No | automated | `Account.account_key` |
| `source` | STRING | No | automated | `Account.source` |
| `source_account_id` | STRING | No | automated | `Account.source_account_id`; preserve as string |
| `name` | STRING | No | automated | `Account.name` |
| `institution` | STRING | Yes | automated | `Account.institution` |
| `account_type` | STRING | No | automated | `Account.account_type` |
| `owner` | STRING | Yes | automated | `Account.owner` |
| `currency` | STRING | No | automated | `Account.currency` |
| `market_value_eur` | NUMBER | Yes | automated | `Account.market_value_eur` |
| `last_seen_at` | DATETIME | No | derived | Successful `PortfolioSnapshot.generated_at` |
| `last_seen_run_id` | STRING | No | derived | Run that last returned the account |
| `is_active` | BOOLEAN | No | derived | Presence in the latest complete snapshot |

Synthetic example:

```text
finary:account:account-demo-001 | finary | account-demo-001 | Demo Investment Account | Example Institution | Securities | [blank] | EUR | 1000.00 | 2026-08-20T07:30:12+02:00 | 20260820-073012 | TRUE
finary:account:account-demo-old | finary | account-demo-old | Closed Demo Account | [blank] | Securities | [blank] | EUR | 25.00 | 2026-08-19T07:30:12+02:00 | 20260819-073012 | FALSE
```

## 6. `positions_current`

Purpose: one row per normalized account-position combination in the latest
known valid state. Ownership is mixed: direct Phase 3 fields are automated;
account enrichment, final classification, weight, and lifecycle fields are
derived. Unique key: `position_key`.

Update: upsert by the complete category-aware `position_key`. A position absent
from a later complete snapshot becomes inactive; retain it and do not set its
value to zero. Never delete automatically.

| Column | Type | Nullable | Owner | Phase 3 source / derivation |
| --- | --- | --- | --- | --- |
| `position_key` | STRING | No | automated | `Position.position_key` |
| `source` | STRING | No | automated | `Position.source` |
| `source_asset_id` | STRING | No | automated | `Position.source_asset_id` |
| `account_key` | STRING | No | automated | `Position.account_key` |
| `account_name` | STRING | No | derived | Join `accounts_current.name` by `account_key` |
| `account_type` | STRING | No | derived | Join `accounts_current.account_type` |
| `institution` | STRING | Yes | derived | Join `accounts_current.institution` |
| `name` | STRING | Yes | automated | `Position.name` |
| `ticker` | STRING | Yes | automated | `Position.ticker` |
| `isin` | STRING | Yes | automated | `Position.isin` |
| `asset_class` | ENUM | No | derived | `Position.asset_class`, then matching `asset_overrides` |
| `asset_subclass` | STRING | Yes | derived | `Position.asset_subclass`, then override |
| `region` | STRING | Yes | derived | `Position.region`, then override |
| `quantity` | NUMBER | Yes | automated | `Position.quantity` |
| `unit_price` | NUMBER | Yes | automated | `Position.unit_price` |
| `currency` | STRING | Yes | automated | `Position.currency` |
| `fx_to_eur` | NUMBER | Yes | automated | `Position.fx_to_eur` |
| `market_value_native` | NUMBER | No | automated | `Position.market_value_native` |
| `market_value_eur` | NUMBER | Yes | automated | `Position.market_value_eur` |
| `cost_basis_eur` | NUMBER | Yes | automated | `Position.cost_basis_eur` |
| `unrealized_pnl_eur` | NUMBER | Yes | automated | `Position.unrealized_pnl_eur` |
| `unrealized_pnl_pct` | NUMBER | Yes | automated | `Position.unrealized_pnl_pct` |
| `weight_portfolio` | NUMBER | Yes | derived | Known EUR value divided by known-EUR active-position denominator |
| `last_seen_at` | DATETIME | No | derived | Successful `PortfolioSnapshot.generated_at` |
| `last_seen_run_id` | STRING | No | derived | Run that last returned the position |
| `is_active` | BOOLEAN | No | derived | Presence in latest complete snapshot |

`weight_portfolio` is blank when the row has no `market_value_eur` or the
known-EUR denominator is zero. When populated, it measures only the subset of
active positions with known EUR values. It is an analytical coverage measure,
not a claim that positions reconcile to authoritative gross assets.

Synthetic examples:

```text
finary:account-demo-001:asset:securities:1001 | finary | securities:1001 | finary:account:account-demo-001 | Demo Investment Account | Securities | Example Institution | Synthetic Index Asset | SYN | XX0000000001 | OTHER | [blank] | [blank] | 2 | 500 | EUR | 1 | 1000 | 1000 | 900 | [blank] | [blank] | 1 | 2026-08-20T07:30:12+02:00 | 20260820-073012 | TRUE
finary:account-demo-002:asset:cryptos:1001 | finary | cryptos:1001 | finary:account:account-demo-002 | Demo Crypto Account | Crypto | [blank] | Synthetic Token | SYNX | [blank] | CRYPTO | [blank] | [blank] | 2 | 25 | [blank] | [blank] | 50 | [blank] | 40 | [blank] | [blank] | [blank] | 2026-08-20T07:30:12+02:00 | 20260820-073012 | TRUE
```

The examples deliberately reuse numeric ID `1001` across `securities` and
`cryptos`; the category-aware IDs remain distinct.

## 7. `liabilities_current`

Purpose: forward-compatible current liability state. Phase 3 has a stable
`Liability` model but no verified callable liability source, so this sheet may
remain empty. An empty sheet does **not** prove that the user has no liabilities.

Ownership: automated and derived lifecycle fields. Unique key:
`liability_key`. Update only from a successful snapshot that explicitly has
complete liability coverage. `FINARY_FEATURE_UNAVAILABLE` must not create a
zero row, clear prior rows, or mark prior rows inactive. Never delete rows.

| Column | Type | Nullable | Owner | Phase 3 source / derivation |
| --- | --- | --- | --- | --- |
| `liability_key` | STRING | No | automated | `Liability.liability_key` |
| `source` | STRING | No | automated | `Liability.source` |
| `source_liability_id` | STRING | No | automated | `Liability.source_liability_id` |
| `name` | STRING | No | automated | `Liability.name` |
| `liability_type` | STRING | No | automated | `Liability.liability_type` |
| `institution` | STRING | Yes | automated | `Liability.institution` |
| `outstanding_eur` | NUMBER | No | automated | `Liability.outstanding_eur` |
| `interest_rate` | NUMBER | Yes | automated | `Liability.interest_rate` |
| `monthly_payment_eur` | NUMBER | Yes | automated | `Liability.monthly_payment_eur` |
| `end_date` | DATE | Yes | automated | `Liability.end_date` |
| `last_seen_at` | DATETIME | No | derived | Successful snapshot timestamp |
| `last_seen_run_id` | STRING | No | derived | Run that last returned the liability |
| `is_active` | BOOLEAN | No | derived | Presence in a complete liability collection |

No sample liability row is supplied because that could imply current upstream
support. The header definition itself is the synthetic forward-compatible
example.

## 8. `positions_history`

Purpose: one historical row per Europe/Paris business date and position.
Ownership: automated snapshot fields and derived keys/final classifications.
Unique key: `history_key = {snapshot_date}:{position_key}`.

The same position on the same date updates the same row. The next date creates
a new row. Historical rows and null EUR values are never deleted or rewritten
as zero. `snapshot_date` is the Europe/Paris calendar date derived from the
timezone-aware `generated_at` value.

| Column | Type | Nullable | Owner | Phase 3 source / derivation |
| --- | --- | --- | --- | --- |
| `history_key` | STRING | No | derived | `{snapshot_date}:{Position.position_key}` |
| `snapshot_date` | DATE | No | derived | Europe/Paris date of `generated_at` |
| `generated_at` | DATETIME | No | automated | `PortfolioSnapshot.generated_at` |
| `position_key` | STRING | No | automated | `Position.position_key` |
| `account_key` | STRING | No | automated | `Position.account_key` |
| `source_asset_id` | STRING | No | automated | `Position.source_asset_id` |
| `name` | STRING | Yes | automated | `Position.name` |
| `ticker` | STRING | Yes | automated | `Position.ticker` |
| `isin` | STRING | Yes | automated | `Position.isin` |
| `asset_class` | ENUM | No | derived | Final classification after override |
| `asset_subclass` | STRING | Yes | derived | Final classification after override |
| `quantity` | NUMBER | Yes | automated | `Position.quantity` |
| `unit_price` | NUMBER | Yes | automated | `Position.unit_price` |
| `currency` | STRING | Yes | automated | `Position.currency` |
| `fx_to_eur` | NUMBER | Yes | automated | `Position.fx_to_eur` |
| `market_value_eur` | NUMBER | Yes | automated | `Position.market_value_eur` |
| `cost_basis_eur` | NUMBER | Yes | automated | `Position.cost_basis_eur` |

Synthetic same-day key:
`2026-08-20:finary:account-demo-001:asset:securities:1001`. A rerun on
2026-08-20 updates it; the 2026-08-21 snapshot creates a different key.

## 9. `portfolio_daily`

Purpose: one validated summary row per Europe/Paris business date. Ownership is
automated for direct snapshot totals and derived for analytical breakdowns.
Unique key: `snapshot_date`; same-day reruns upsert, rows are never deleted.

Only a complete successful snapshot may write this sheet. Phase 3 currently
returns no snapshot at all when liability coverage is unavailable, so Phase 5
must leave the prior daily/current state untouched and record failed telemetry.
The nullable liability and net-worth columns preserve unknown semantics for
future contract evolution or imported historical rows; blank never means zero.

| Column | Type | Nullable | Owner | Source / derivation |
| --- | --- | --- | --- | --- |
| `snapshot_date` | DATE | No | derived | Europe/Paris date of `generated_at` |
| `generated_at` | DATETIME | No | automated | `PortfolioSnapshot.generated_at` |
| `gross_assets_eur` | NUMBER | No | automated | `PortfolioSnapshot.gross_assets_eur`; authoritative account total |
| `liabilities_eur` | NUMBER | Yes | automated | `PortfolioSnapshot.liabilities_eur` when known |
| `net_worth_eur` | NUMBER | Yes | automated | `PortfolioSnapshot.net_worth_eur` when known |
| `financial_assets_eur` | NUMBER | Yes | derived | Known-EUR active financial-position subset; not currently fully definable |
| `equity_eur` | NUMBER | Yes | derived | Known-EUR active `EQUITY` positions |
| `bond_eur` | NUMBER | Yes | derived | Known-EUR active `BOND` positions |
| `cash_eur` | NUMBER | Yes | derived | Known-EUR active `CASH` positions |
| `real_estate_eur` | NUMBER | Yes | derived | Known-EUR active `REAL_ESTATE` positions |
| `scpi_eur` | NUMBER | Yes | derived | Known-EUR active `SCPI` positions |
| `private_equity_eur` | NUMBER | Yes | derived | Known-EUR active `PRIVATE_EQUITY` positions |
| `crypto_eur` | NUMBER | Yes | derived | Known-EUR active `CRYPTO` positions |
| `commodity_eur` | NUMBER | Yes | derived | Known-EUR active `COMMODITY` positions |
| `life_insurance_fund_eur` | NUMBER | Yes | derived | Known-EUR active `LIFE_INSURANCE_FUND` positions |
| `other_eur` | NUMBER | Yes | derived | Known-EUR active `OTHER` positions |
| `equity_pct` | NUMBER | Yes | derived | `equity_eur / known-EUR active position total` |
| `bond_pct` | NUMBER | Yes | derived | `bond_eur / known-EUR active position total` |
| `cash_pct` | NUMBER | Yes | derived | `cash_eur / known-EUR active position total` |
| `real_estate_pct` | NUMBER | Yes | derived | `real_estate_eur / known-EUR active position total` |
| `scpi_pct` | NUMBER | Yes | derived | `scpi_eur / known-EUR active position total` |
| `private_equity_pct` | NUMBER | Yes | derived | `private_equity_eur / known-EUR active position total` |
| `crypto_pct` | NUMBER | Yes | derived | `crypto_eur / known-EUR active position total` |
| `commodity_pct` | NUMBER | Yes | derived | `commodity_eur / known-EUR active position total` |
| `life_insurance_fund_pct` | NUMBER | Yes | derived | `life_insurance_fund_eur / known-EUR active position total` |
| `other_pct` | NUMBER | Yes | derived | `other_eur / known-EUR active position total` |
| `pea_eur` | NUMBER | Yes | derived | Known-EUR accounts with stable PEA account type |
| `cto_eur` | NUMBER | Yes | derived | Known-EUR accounts with stable CTO account type |
| `life_insurance_eur` | NUMBER | Yes | derived | Known-EUR accounts with stable life-insurance type |
| `cash_accounts_eur` | NUMBER | Yes | derived | Known-EUR accounts with stable cash type |
| `run_id` | STRING | No | derived | Producing synchronization run |

Asset-class totals and percentages can be partial because Phase 3 correctly
leaves some position EUR values blank. Percentages exclude liabilities and use
only active positions with known EUR values. They must be presented as
known-EUR allocation coverage, not as a reconciliation to `gross_assets_eur`.
`financial_assets_eur` remains blank unless Phase 5 can prove a complete,
non-overlapping definition; Phase 4 does not invent one.

Synthetic example: `2026-08-20 | 2026-08-20T07:30:12+02:00 | 1000 | [blank] |
[blank] | [blank] | ... | 20260820-073012`. The blanks demonstrate unknown
liability/net-worth and analytical values; they are not zero.

## 10. `allocation_targets`

Purpose: entirely manual target ranges. Unique key: `target_key`. Sync may read
but never create, update, deactivate, or delete these rows.

| Column | Type | Nullable | Owner | Meaning |
| --- | --- | --- | --- | --- |
| `target_key` | STRING | No | manual | User-defined stable key |
| `asset_class` | ENUM | No | manual | One normalized top-level class |
| `asset_subclass` | STRING | Yes | manual | Optional narrower target |
| `target_pct` | NUMBER | No | manual | Decimal fraction target |
| `min_pct` | NUMBER | No | manual | Decimal fraction lower bound |
| `max_pct` | NUMBER | No | manual | Decimal fraction upper bound |
| `notes` | STRING | Yes | manual | User notes |
| `enabled` | BOOLEAN | No | manual | Whether Phase 5 should consider the row |

For each enabled row: `0 <= min_pct <= target_pct <= max_pct <= 1`.
Synthetic example:
`equity-demo | EQUITY | [blank] | 0.75 | 0.70 | 0.80 | Synthetic target | TRUE`.

## 11. `asset_overrides`

Purpose: entirely manual, authoritative corrections to automatic position
classification. Unique key: `override_key`. Sync reads but never overwrites or
deletes rows.

| Column | Type | Nullable | Owner | Meaning |
| --- | --- | --- | --- | --- |
| `override_key` | STRING | No | manual | User-defined stable key |
| `source_asset_id` | STRING | Yes | manual | Exact category-aware `{position_kind}:{asset_id}` |
| `isin` | STRING | Yes | manual | Exact ISIN match |
| `ticker` | STRING | Yes | manual | Exact ticker match |
| `name_match` | STRING | Yes | manual | Exact normalized name match; no fuzzy matching |
| `custom_asset_class` | ENUM | Yes | manual | Replacement top-level class |
| `custom_asset_subclass` | STRING | Yes | manual | Replacement subclass |
| `custom_region` | STRING | Yes | manual | Replacement region |
| `notes` | STRING | Yes | manual | User notes |
| `enabled` | BOOLEAN | No | manual | Whether the override participates |

At least one matcher and at least one replacement value are required for an
enabled row. Matching precedence is exactly:

1. exact `source_asset_id`;
2. exact `isin`;
3. exact `ticker`;
4. exact normalized `name_match`.

No fuzzy matching is allowed. Multiple enabled matches at the same highest
precedence are a Phase 5 validation error.

Synthetic example:
`override-demo-001 | securities:1001 | [blank] | [blank] | [blank] | EQUITY |
WORLD_EQUITY | GLOBAL | Synthetic override | TRUE`.

## 12. `cashflows`

Purpose: initially manual EUR cashflows. Unique key: `cashflow_key`. Portfolio
sync must never overwrite or delete rows. Phase 4 defines no performance
calculation.

| Column | Type | Nullable | Owner | Meaning |
| --- | --- | --- | --- | --- |
| `cashflow_key` | STRING | No | manual | User-defined stable key |
| `date` | DATE | No | manual | Europe/Paris business date |
| `account_key` | STRING | No | manual | Existing `accounts_current.account_key` |
| `amount_eur` | NUMBER | No | manual | Explicit EUR amount |
| `type` | ENUM | No | manual | Cashflow type enum |
| `notes` | STRING | Yes | manual | User notes |
| `source` | STRING | No | manual | Origin, initially `manual` |

Allowed types: `CONTRIBUTION`, `WITHDRAWAL`, `DIVIDEND`, `INTEREST`, `FEE`,
`TAX`, `TRANSFER`.

Sign convention:

- positive: `CONTRIBUTION`, `DIVIDEND`, `INTEREST`;
- negative: `WITHDRAWAL`, `FEE`, `TAX`;
- `TRANSFER`: signed from the referenced account's perspective. An internal
  transfer should use paired equal-and-opposite rows and must be excluded from
  external performance-flow totals.

Synthetic example:
`cashflow-demo-001 | 2026-08-20 | finary:account:account-demo-001 | 100.00 |
CONTRIBUTION | Synthetic contribution | manual`.

## 13. `sync_runs`

Purpose: append-oriented synchronization telemetry, not portfolio state.
Ownership: derived. Unique key: `run_id`, formatted `YYYYMMDD-HHMMSS` in
Europe/Paris. One terminal row is appended per run; a retry using the same
`run_id` may update only that telemetry row. Rows are never deleted.

| Column | Type | Nullable | Owner | Source / meaning |
| --- | --- | --- | --- | --- |
| `run_id` | STRING | No | derived | Run context |
| `started_at` | DATETIME | No | derived | Timezone-aware start |
| `completed_at` | DATETIME | No | derived | Timezone-aware completion |
| `status` | ENUM | No | derived | `SUCCESS`, `SUCCESS_WITH_WARNINGS`, or `FAILED` |
| `accounts_count` | NUMBER | Yes | derived | Validated snapshot count, blank on early failure |
| `positions_count` | NUMBER | Yes | derived | Validated snapshot count, blank on early failure |
| `liabilities_count` | NUMBER | Yes | derived | Validated snapshot count, blank when unavailable |
| `gross_assets_eur` | NUMBER | Yes | derived | Snapshot total when available |
| `liabilities_eur` | NUMBER | Yes | derived | Snapshot total when available |
| `net_worth_eur` | NUMBER | Yes | derived | Snapshot total when available |
| `previous_net_worth_eur` | NUMBER | Yes | derived | Prior successful daily value when known |
| `net_worth_change_pct` | NUMBER | Yes | derived | Decimal fraction when both values are known |
| `duration_ms` | NUMBER | No | derived | Non-negative elapsed milliseconds |
| `bridge_version` | STRING | Yes | derived | Bridge version if obtained |
| `schema_version` | STRING | Yes | derived | Snapshot schema version if obtained |
| `warning_count` | NUMBER | No | derived | Non-negative warning count |
| `error_code` | STRING | Yes | derived | Stable error code on failure |
| `error_message` | STRING | Yes | derived | Sanitized error text, never raw secrets/payloads |

A failed run may contain blanks for every portfolio count and value. Zero must
not be used as an error placeholder. Synthetic failed example:

```text
20260820-073012 | 2026-08-20T07:30:12+02:00 | 2026-08-20T07:30:13+02:00 | FAILED | [blank] | [blank] | [blank] | [blank] | [blank] | [blank] | [blank] | [blank] | 1000 | 0.1.0 | [blank] | 0 | FINARY_FEATURE_UNAVAILABLE | Required Finary data is unavailable
```

## 14. Initialization and Phase 5 boundary

The JSON definition is sufficient for a safe manual bootstrap helper to:

- create the ten named sheets;
- write their ordered header rows;
- initialize the `README` dictionary rows;
- configure enum and boolean validation;
- configure percentage display formatting without changing stored fractions.

It intentionally cannot authenticate with Google or create a live workbook.
Phase 5 must implement synchronization separately and preserve these rules:

1. Validate a complete bridge response before any portfolio write.
2. On a structured bridge error, write failed `sync_runs` telemetry only.
3. Never replace blanks with zero.
4. Never clear a sheet.
5. Never overwrite the three manual sheets.
6. Apply overrides deterministically before writing final classifications.
7. Upsert current/history/daily rows by the documented keys.
8. Mark missing current rows inactive only from a complete valid snapshot.
9. Keep account totals separate from analytical position totals.
10. Treat known-EUR position allocation as potentially partial coverage.
