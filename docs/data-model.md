# Google Sheets data model

## Canonical contract

The workbook is named **Finary Portfolio Data** and uses schema `2.1`.
[`google-sheets-schema.json`](google-sheets-schema.json) is the single
machine-readable source for ordered sheet names, headers, types, nullability,
ownership, enums, and key formats. This guide explains how to interpret and
operate that contract; it does not duplicate every column.

The workbook uses ten sheets in a fixed order:

| Sheet | Ownership | Unique key | Purpose |
| --- | --- | --- | --- |
| `README` | automated reference | `key` | Workbook-readable semantic rules |
| `accounts_current` | automated | `account_key` | Physical account rows requiring membership validation, including inactive rows |
| `positions_current` | automated and derived | `position_key` | Physical positions and classification requiring completeness validation |
| `liabilities_current` | automated | `liability_key` | Physical liability rows requiring independent COMPLETE-run validation |
| `positions_history` | automated and derived | `history_key` | Daily position valuations with successful-run membership |
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
Portfolio synchronization does not rewrite the initialized `README`. Existing
installations must adopt the [consumer-validation updates](operations.md#consumer-validation-adoption)
and replace the uploaded knowledge reference. No column migration is needed for
this interpretation correction.

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
run_id          = n8n-execution:{execution_id}
```

The position kind is part of both asset identifiers because equal numeric IDs
may occur in separate upstream collections. Do not shorten these keys in
Sheets.

`run_id` is an opaque identity derived once from n8n's persisted execution ID.
It is independent of timestamps, ordering, timezone, and daylight-saving
transitions. Timestamp-shaped identifiers written by older workflow versions
remain valid legacy strings and must not be rewritten or interpreted as current
n8n execution IDs.

## Current state and retention

`accounts_current`, `positions_current`, and `liabilities_current` use
deterministic upserts. Missing accounts or positions are retained with
`is_active = FALSE`; they are not deleted. These physical tables can be
partially overwritten by an unsuccessful execution. They do not unconditionally
represent a successful portfolio snapshot.

Select the latest unambiguous successful execution using parsed timezone-aware
`completed_at`, then validate full current account and position tables before
filtering. Require non-empty unique canonical keys and valid activity flags on
all rows; every active `last_seen_run_id` must equal that successful `run_id`.
Active counts must match its finite non-negative integer `accounts_count` and
`positions_count`. Native numbers and decimal numeric strings are supported;
missing/blank counts and booleans are not zero. Activity accepts native booleans
or exact `TRUE`/`FALSE`, never numeric 0/1 or other strings. Reject foreign-run,
extra, missing, or duplicate rows instead of filtering or deduplicating them to
make counts pass. Active positions must reference validated active accounts;
when joined to validated same-run history, position-key sets must agree.

Only after these checks can `is_active = TRUE` represent complete holdings.
Inactive rows do not count; their `last_seen_run_id` and `last_seen_at` retain the
last observation even when a newer execution writes the inactivation. An older
inactive ID alone is allowed. Failed inactivation may instead reduce prior-run
active membership, which the count checks must detect. If either current asset
table fails, reject the combined current state and use independently validated
history or report the requested details unavailable.

Liability rows are different: they may be updated or inactivated only from a
snapshot whose `liability_coverage` is `COMPLETE`. `PARTIAL` or `UNAVAILABLE`
must not modify, clear, or inactivate prior liability state.

`positions_history` retains one row per business date and position. The same
`history_key` updates the same-day row and its `run_id`; the next date creates a
new row. A position absent from a later same-day run keeps its older row, but
that row is not a member of the later run. Historical rows are never
automatically deleted. `portfolio_daily` similarly upserts one summary per
`snapshot_date` and records the run that wrote it.

An invalid snapshot is rejected before portfolio writes. Google Sheets writes
are not transactional, so an execution failure can leave partial current,
history, or daily writes. Such an attempt has no successful terminal marker and
cannot be treated as complete under the selection rule below.

Native retries performed by a node inside one execution keep the same
`run_id` and deterministic row keys. n8n's saved-data retry creates a new n8n
execution while retaining earlier node output. The workflow therefore refuses
to publish its terminal success when the saved `run_id` differs from the
current n8n execution ID. Except for retrying the already-reached terminal
Sheets write itself, recover with a full new workflow execution so a fresh
snapshot receives a fresh identity.

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

Validate liability details against the latest unambiguous successful `COMPLETE`
run independently of newer incomplete asset runs. Inspect the full liability
table for unique non-empty canonical keys and valid activity flags, then require
every active row's `last_seen_run_id` and the active count to match that run and
its valid `liabilities_count`. Retained inactive rows do not count and may carry
older observation IDs. Verify finite outstanding amounts against the complete
total and consistent observation timestamps. A newer same-day daily row does
not invalidate these independently proven details. Failed `COMPLETE` rewrites
or inactivations make details unavailable; no liability history exists.

An empty active set proves zero only with successful `COMPLETE` evidence, valid
zero count and zero total. Report the separate complete run, completion time and
retained snapshot date; if zero rows and no matching daily row survive, the
exact snapshot date is unavailable. Never subtract older last-known liabilities
from newer gross assets to claim authoritative current net worth. A validated
daily aggregate can remain available even when detailed liability rows fail.

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

`sync_runs` is intended to store one terminal row per run. `SUCCESS` and
`SUCCESS_WITH_WARNINGS` are completed executions; `FAILED` is not. Select by
parsed timezone-aware `completed_at`, never by opaque `run_id` or row order.
Require exactly one terminal record for a candidate across all statuses; reject
duplicates, conflicting success/failure evidence, missing timestamps, and tied
newest instants. A later failure does not replace a success, but absence of a
failure does not prove success. The latest successful execution differs from
the latest state whose required rows remain available and valid.

For a date, require one `portfolio_daily` row, valid business date and
`generated_at`, and one matching successful terminal record. Shared totals and
coverage must agree and preserve unknown-value semantics. This independently
validates stored daily aggregates, including authoritative `gross_assets_eur`.

For position detail, check canonical history keys and unique non-empty position
keys across all history rows for the date before filtering. Select only rows
with that daily `run_id`, requiring valid `positions_count` and matching
`generated_at`. Distinct retained keys from earlier runs are excluded; never
borrow them to fill missing members. A successful terminal record cannot
recover history overwritten by a later same-day attempt. Do not use position
sums versus gross assets as a completeness check.

If current asset data fails, examine historical states in descending business
date order, using only those passing these independent checks. Explicitly label
any fallback with its date, run ID, completion time and freshness limitation
(stale after 48 hours); otherwise report the requested data unavailable. Limit
answers to stored history fields or safe derivations. No enrichment from invalid
current rows, invented historical account metadata or regions, reconstructed
account balances, or invented liability details is allowed. Blank EUR fields
stay unknown and allocation may cover only the known-EUR subset. Validated
daily aggregates remain separately usable if position detail fails; disclose
their own provenance when different from a historical fallback.

The [knowledge reference](finary-portfolio-data-knowledge.md) specifies the full
reading procedure. The [test-only executable specification](../finary-bridge/tests/workbook_consumer.py)
and [regressions](../finary-bridge/tests/test_workbook_consumer.py) exercise it
using exported Code-node preparation; they are not a deployed validator and do
not automatically enforce it inside ChatGPT. Sequential Sheets reads cannot
create a transactional snapshot: reject observed changes and inconsistencies,
repeat the full read after writes settle, and disclose unresolved consistency.
Even identical repeated reads cannot exclude an unobserved concurrent write.

Financial totals in failed rows remain blank rather than using zero as an error
placeholder. Errors contain stable, sanitized codes and messages. The table is
telemetry, not portfolio state, and is retained append-style.

Rows written before schema `2.1` have a blank `positions_history.run_id`. They
remain legacy valuations but cannot be proven to be complete snapshot
membership. They are excluded from the rule above.

## Schema changes

Add or reorder a column only by updating the canonical JSON, workflow mappings,
tests, and consumer documentation together. Preserve blank/null semantics,
ownership boundaries, category-aware IDs, and deterministic keys. A breaking
contract change requires a new schema major version rather than an in-place
reinterpretation of existing columns.
