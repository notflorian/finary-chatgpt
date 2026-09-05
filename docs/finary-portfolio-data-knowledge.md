# Finary Portfolio Data — ChatGPT knowledge reference

## Purpose and authority

This file is reference material for interpreting the canonical private Google
workbook named **Finary Portfolio Data**. It describes the workbook's stable
schema and financial-data semantics. It does not contain investment-policy
rules and does not replace the ChatGPT Project's behavioral Instructions or the
separate **Personal Investment Policy** reference document.

When portfolio data is needed, use the live canonical workbook through the
linked Google Drive source in the private ChatGPT Project. The currently
verified personal-account custom GPT surface does not expose Google Drive, so
do not use this file inside a custom GPT as a substitute for live workbook
access. Reject backup, test, exported, obsolete v1, or similarly named copies.
Read the workbook's `README` tab before interpreting the other tabs. The
workbook is the factual source for portfolio state; this file explains how to
interpret it.

## Workbook tabs

The canonical workbook schema version is `2.1` and contains exactly these ten tabs:

- `README`: human- and machine-readable interpretation rules for the workbook.
- `accounts_current`: latest known valid normalized accounts, including
  retained inactive rows.
- `positions_current`: latest known valid normalized positions, including
  retained inactive rows and final classifications after manual overrides.
- `liabilities_current`: last authoritative liability rows obtained with
  `COMPLETE` liability coverage; it may be empty or older than current assets.
- `positions_history`: daily position valuations. A position has at most one
  row per Europe/Paris business date, and `run_id` identifies its snapshot
  membership.
- `portfolio_daily`: one daily portfolio summary, including authoritative gross
  assets, liability coverage, nullable liability-dependent totals, and
  analytical position breakdowns.
- `allocation_targets`: user-maintained target allocation ranges. Percentages
  are decimal fractions, so `0.25` means 25%.
- `asset_overrides`: user-maintained exact-match corrections to automatic asset
  classification.
- `cashflows`: user-maintained EUR cashflows used only when sufficiently
  complete for performance analysis.
- `sync_runs`: append-oriented synchronization telemetry. It is not portfolio
  state.

## Selecting the latest valid synchronization

Use `sync_runs` and select the row with the newest valid `completed_at` among
rows whose `status` is `SUCCESS` or `SUCCESS_WITH_WARNINGS`. Compare parsed
timestamps, not physical row order and not `run_id` ordering. A later `FAILED`
row does not replace the latest valid synchronization and does not advance data
freshness.

For a complete position state on a given Europe/Paris date, start with its
single `portfolio_daily` row. Require exactly one `sync_runs` row with the same
`run_id`, a status of `SUCCESS` or `SUCCESS_WITH_WARNINGS`, and a parseable
`completed_at`. Keep only `positions_history` rows with that date and `run_id`.
Use the state only if the row count equals `sync_runs.positions_count` and
position keys are unique. If any check fails, report that date as unusable
until a successful retry; do not combine rows from another run. When daily
production is expected, a latest valid run older than 48 hours is stale. State
the completion time and freshness limitation before using stale data.

A missing position has no row in the selected run membership. Its retained
same-date row may belong to an older run and must be excluded; absence never
means a zero valuation. Rows with blank `run_id` predate schema `2.1` and are
legacy valuations whose complete membership cannot be established.

## Synchronization statuses and warnings

- `SUCCESS`: all portfolio writes completed and no warning was generated.
- `SUCCESS_WITH_WARNINGS`: all intended writes completed, but coverage is
  incomplete or a monitoring threshold was crossed. The state is valid subject
  to the stated warnings.
- `FAILED`: synchronization did not produce a new valid portfolio state.
  Financial fields may be blank. Preserve and use the prior valid state.

`warning_count` gives the number of warnings. When present, `error_message` on a
successful run contains comma-separated warning codes rather than a failure.
Relevant codes are:

- `LIABILITY_COVERAGE_PARTIAL`: only a non-exhaustive liability subset is
  available.
- `LIABILITY_COVERAGE_UNAVAILABLE`: no authoritative current liability
  collection is available.
- `PARTIAL_POSITION_EUR_COVERAGE`: at least one position lacks a verified EUR
  market value, so position-derived allocation covers only the known-EUR
  subset.
- `ACCOUNT_COUNT_CHANGE_OVER_30_PERCENT`: active account count changed by more
  than the monitoring threshold.
- `POSITION_COUNT_CHANGE_OVER_30_PERCENT`: active position count changed by
  more than the monitoring threshold.
- `NET_WORTH_CHANGE_OVER_20_PERCENT`: known net worth changed by more than the
  monitoring threshold. This is a warning, not proof of performance or error.

## Current-state rows and `is_active`

For current accounts, positions, or liabilities, include only rows where
`is_active = TRUE`, unless the user explicitly asks for closed, disappeared, or
historical records. Rows with `is_active = FALSE` are deliberately retained for
auditability. They are not currently held and their retained values must not be
added to current totals.

A missing account or position in a later valid asset snapshot becomes inactive
rather than being deleted or set to zero. Liability rows may be changed or
inactivated only by a snapshot whose liability coverage is `COMPLETE`.

## Blank cells and null values

A blank cell means **unknown, unavailable, or not safely derivable**. It never
means zero, none, false, or not applicable unless another explicit field proves
that interpretation. Zero is a real observed or calculated number and remains
distinct from a blank.

Do not replace blank numeric cells with zero. Do not average, total, compare, or
calculate percentages from blanks as though they were zeros. State the missing
coverage when it affects an answer.

## Currency and EUR values

The workbook reference currency is EUR. A field ending in `_eur` is populated
only when EUR provenance is verified by the bridge or a verified conversion is
available. No EUR amount is inferred from an upstream display value. No
speculative foreign-exchange conversion is performed.

For positions, `currency`, `fx_to_eur`, `market_value_eur`, `cost_basis_eur`,
and other EUR-derived fields may legitimately be blank. `market_value_native`
does not become EUR merely because the workbook uses EUR as its reference
currency. Never relabel a native amount as EUR.

## Gross assets and double-counting

The authoritative gross-assets figure is
`portfolio_daily.gross_assets_eur` from the latest valid daily state. It is
produced from normalized account balances under the bridge's exclusion rules.

Position values are analytical components that can overlap those account
balances. Never calculate gross assets by adding account balances and position
values. Never substitute a sum of positions for authoritative gross assets.
Account totals may be used only as a consistency check when their EUR values
are known.

## Liabilities and net worth

`portfolio_daily.liability_coverage` is authoritative and has three values:

- `COMPLETE`: current liability rows and totals are authoritative. A numeric
  `liabilities_eur` may be used, and `net_worth_eur` may be reported.
- `PARTIAL`: some liabilities may be known, but the set is not exhaustive.
  Current total liabilities and net worth are not authoritative and remain
  blank.
- `UNAVAILABLE`: no authoritative current liability collection is available.
  Current total liabilities and net worth remain blank.

Under `PARTIAL` or `UNAVAILABLE`, do not conclude that the user has no debt, do
not treat liabilities as zero, and do not equate gross assets with net worth.
`liabilities_current` may contain rows retained from the last `COMPLETE`
snapshot; describe them only as last-known complete liability data, not current
liabilities. An empty `liabilities_current` tab does not prove zero liabilities.

## Partial position coverage and allocation

Allocation values and `weight_portfolio` use active positions with a known
`market_value_eur`. Liabilities are excluded. A position with a blank EUR value
has a blank weight. If the known-EUR denominator is zero, all allocation
percentages are blank.

When `PARTIAL_POSITION_EUR_COVERAGE` is present, describe allocation as the
distribution of the active known-EUR position subset. Do not present it as the
full portfolio allocation and do not reconcile that subset to authoritative
gross assets. Asset-class totals can also be blank when their class contains an
unknown-EUR position. `financial_assets_eur` is nullable because no reliable,
non-overlapping definition is guaranteed by the current contract.

## Valuation history versus investment performance

`positions_history` and `portfolio_daily` show valuation and composition over
time. Differences between dates may result from market movement, contributions,
withdrawals, transfers, reclassification, coverage changes, or data changes.
They are not, by themselves, investment returns.

Describe a simple difference as a **valuation change** or **composition
change**. Calculate or label investment performance, return, gain attributable
to markets, time-weighted return, money-weighted return, or XIRR only when the
required cashflows are sufficiently complete and the chosen methodology is
explicitly stated. The current pipeline does not automatically calculate
performance.

## Cashflow requirements

The `cashflows` tab is initially user-maintained and synchronization never
overwrites it. Each row has an explicit EUR `amount_eur`, a date, an account
key, a stable cashflow key, a source, and one of these types:

`CONTRIBUTION`, `WITHDRAWAL`, `DIVIDEND`, `INTEREST`, `FEE`, `TAX`, `TRANSFER`.

The sign convention is:

- positive: `CONTRIBUTION`, `DIVIDEND`, `INTEREST`;
- negative: `WITHDRAWAL`, `FEE`, `TAX`;
- `TRANSFER`: signed per account; paired equal-and-opposite internal transfers
  are excluded from external portfolio flows.

Before calculating performance, verify that external cashflows are complete for
the entire requested period and relevant accounts, dates, and flow types. If
completeness cannot be established, do not calculate or imply performance;
state that only valuation changes can be measured reliably.

## Identifier and date formats

Identifiers are deterministic strings and must not be reconstructed from names,
tickers, or ISINs:

- account key: `finary:account:{account_id}`
- source asset ID: `{position_kind}:{asset_id}`
- position key: `finary:{account_id}:asset:{position_kind}:{asset_id}`
- history key: `{snapshot_date}:{position_key}`
- daily portfolio key: `{snapshot_date}`
- synchronization run ID: opaque `n8n-execution:{execution_id}` for current
  runs; older timestamp-shaped IDs remain valid legacy strings

The position kind is part of position identity because the same numeric asset ID
may exist in different upstream categories. Preserve category-aware IDs exactly.

Business dates use `YYYY-MM-DD` in the `Europe/Paris` timezone. Timestamps are
ISO 8601 with an explicit timezone offset. Parse timestamps as instants before
comparison; do not treat an ambiguous local timestamp or lexical row order as
chronological authority.

Treat `run_id` as an opaque equality key. Never sort it, parse a timestamp from
it, or reconstruct it from a business date.
