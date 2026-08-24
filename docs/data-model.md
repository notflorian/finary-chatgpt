# Google Sheets data model

## Canonical contract

The workbook is named **Finary Portfolio Data** and uses schema `2.0`.
[`google-sheets-schema.json`](google-sheets-schema.json) is the single
machine-readable source for ordered sheet names, headers, types, nullability,
ownership, enums, and key formats. This guide explains how to interpret and
operate that contract; it does not duplicate every column.

The workbook uses ten sheets in a fixed order:

| Sheet | Ownership | Unique key | Purpose |
| --- | --- | --- | --- |
| `README` | automated reference | `key` | Workbook-readable semantic rules |
| `accounts_current` | automated | `account_key` | Latest valid account state, including inactive rows |
| `positions_current` | automated and derived | `position_key` | Latest valid normalized positions and analytical classification |
| `liabilities_current` | automated | `liability_key` | Last complete liability state, when complete coverage exists |
| `positions_history` | automated and derived | `history_key` | Daily position valuation snapshots |
| `portfolio_daily` | automated and derived | `snapshot_date` | Daily portfolio totals, coverage, and analytical allocation |
| `allocation_targets` | manual | `target_key` | User-defined allocation ranges |
| `asset_overrides` | manual | `override_key` | Exact-match classification corrections |
| `cashflows` | manual | `cashflow_key` | External flows and internal transfers |
| `sync_runs` | derived telemetry | `run_id` | Append-oriented synchronization outcomes |

Portfolio synchronization never writes the three manual sheets. The workbook
contains no raw metadata or private Finary payload column.

## Workbook initialization

Create all ten tabs, then copy each exact header row from the JSON schema. This
command prints one tab's ordered, tab-separated header:

```bash
SHEET=positions_current
jq -r --arg sheet "$SHEET" '.sheets[$sheet].columns | map(.name) | @tsv' \
  docs/google-sheets-schema.json
```

Paste the output into row 1 and repeat for every sheet. Populate `README` with
the objects in `readme_entries`, preserving `key`, `value`, and `description`.
The synchronization workflow validates every required header before preparing
portfolio rows and fails safely on drift.

## Type conventions

The schema uses Sheets-compatible logical types:

- `STRING`: text, including identifiers;
- `NUMBER`: a finite number, never NaN or infinity;
- `BOOLEAN`: `TRUE` or `FALSE` only;
- `DATE`: `YYYY-MM-DD` in `Europe/Paris`;
- `DATETIME`: ISO 8601 with an explicit timezone offset;
- `ENUM`: one of the values listed in the JSON `enums` object.

A nullable value is a blank cell. Blank means unknown, unavailable, or not
applicable; it never means zero. Do not put `N/A`, `unknown`, or the text `null`
in numeric columns. A numeric zero is stored only when zero is actually known.

Percentages are decimal fractions: `0.75` means 75%.

## Identity

Display names, tickers, and ISINs are not primary keys. The stable key formats
are:

```text
account_key     = finary:account:{account_id}
source_asset_id = {position_kind}:{asset_id}
position_key    = finary:{account_id}:asset:{position_kind}:{asset_id}
history_key     = {snapshot_date}:{position_key}
portfolio_daily = {snapshot_date}
run_id          = YYYYMMDD-HHMMSS
```

The position kind is part of both asset identifiers because equal numeric IDs
may occur in separate upstream collections. Do not shorten these keys in
Sheets.

## Current state and retention

`accounts_current`, `positions_current`, and `liabilities_current` use
deterministic upserts. Missing accounts or positions are retained with
`is_active = FALSE`; they are not deleted. Consumers normally filter current
analysis to `is_active = TRUE` while retaining inactive rows for continuity.

Liability rows are different: they may be updated or inactivated only from a
snapshot whose `liability_coverage` is `COMPLETE`. `PARTIAL` or `UNAVAILABLE`
must not modify, clear, or inactivate prior liability state.

`positions_history` retains one row per business date and position. The same
`history_key` updates the same-day row; the next date creates a new row.
Historical rows are never automatically deleted. `portfolio_daily` similarly
upserts one summary per `snapshot_date`.

A failed or invalid snapshot does not update current state, history, or daily
portfolio rows. Only sanitized failure telemetry may be written to `sync_runs`.

## Currency and portfolio totals

EUR-normalized cells are populated only when the bridge proved EUR provenance
or used a verified conversion. A missing `currency`, `fx_to_eur`, or
`market_value_eur` remains blank. Upstream display amounts do not establish EUR.

`gross_assets_eur` is copied from the bridge's authoritative total of eligible
account balances. Position values are analytical detail and must never be added
to account balances. Consequently:

- asset-class totals use only active positions with known `market_value_eur`;
- allocation percentages divide by that known-EUR position subset;
- those analytical totals may not equal gross assets;
- `PARTIAL_POSITION_EUR_COVERAGE` warns that some active positions are omitted
  from the known-EUR analytical subset.

`financial_assets_eur` and account-type aggregates are derived and nullable.
They must not be presented as full portfolio totals unless their required input
coverage is known.

## Liability semantics

`liability_coverage` is one of:

- `COMPLETE`: the snapshot establishes the complete liability collection;
- `PARTIAL`: some liabilities may be represented, but complete coverage is not
  proven;
- `UNAVAILABLE`: no usable liability representation is available.

Only `COMPLETE` permits numeric `liabilities_eur` and `net_worth_eur`. With
incomplete coverage, both cells remain blank. An empty `liabilities_current`
sheet does not prove that the user has no liabilities, and the system never
creates a synthetic zero-liability row.

## Manual analytical inputs

### `allocation_targets`

Each enabled row defines a target range using decimal fractions:

```text
0 <= min_pct <= target_pct <= max_pct <= 1
```

Targets can apply to an asset class and optional subclass. The synchronization
workflow reads no values from this sheet and never overwrites it.

### `asset_overrides`

Enabled rows correct automatic `asset_class`, `asset_subclass`, or `region`.
Matching is exact, with this precedence:

1. category-aware `source_asset_id`;
2. ISIN;
3. ticker;
4. exact normalized `name_match`.

There is no fuzzy matching. Multiple enabled matches at the same precedence are
an error. The workflow reads this sheet and writes final classification only to
automated position rows; it never edits override rows.

### `cashflows`

Allowed types are `CONTRIBUTION`, `WITHDRAWAL`, `DIVIDEND`, `INTEREST`, `FEE`,
`TAX`, and `TRANSFER`. Amounts are explicitly EUR.

- contributions, dividends, and interest are positive;
- withdrawals, fees, and taxes are negative;
- internal transfers use equal-and-opposite account rows and are excluded from
  external portfolio flows.

The current application stores these user inputs but does not calculate
investment performance. Valuation changes in daily or position history are not
returns unless external cashflows are complete and a suitable performance
method is applied separately.

## Synchronization telemetry

`sync_runs` stores one terminal row per run. `SUCCESS` and
`SUCCESS_WITH_WARNINGS` are valid completed states; `FAILED` is not. The newest
valid state is selected by the greatest parseable `completed_at` among the two
successful statuses. A later failed row does not replace it.

Financial totals in failed rows remain blank rather than using zero as an error
placeholder. Errors contain stable, sanitized codes and messages. The table is
telemetry, not portfolio state, and is retained append-style.

## Schema changes

Add or reorder a column only by updating the canonical JSON, workflow mappings,
tests, and consumer documentation together. Preserve blank/null semantics,
ownership boundaries, category-aware IDs, and deterministic keys. A breaking
contract change requires a new schema major version rather than an in-place
reinterpretation of existing columns.
