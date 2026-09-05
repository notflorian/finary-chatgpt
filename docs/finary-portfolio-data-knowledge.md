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
- `accounts_current`: physical normalized accounts, including retained inactive
  rows; successful-run membership must be validated before use.
- `positions_current`: physical normalized positions, including retained inactive
  rows and final classifications after manual overrides; completeness must be
  validated before use.
- `liabilities_current`: physical liability rows written with `COMPLETE` coverage;
  independently validate them because they may be older than assets or partially
  overwritten by an unsuccessful attempt.
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

## Selecting the latest successful execution

Read complete relevant table contents, including every page and physical row;
exclude headers and wholly empty rows only. A search result, sampled range, or
prefiltered subset cannot prove completeness. Use `sync_runs` to identify the
newest valid `completed_at` among `SUCCESS` or `SUCCESS_WITH_WARNINGS` records.
Compare parsed timezone-aware instants, never physical row order or `run_id`.
A later `FAILED` record does not advance freshness. Absence of a `FAILED` record
is not evidence of success.

Require a non-empty run ID and exactly one terminal record for each candidate,
checking all statuses before selecting success. Reject duplicate records,
including conflicting success/failure records; do not silently deduplicate even
identical records. Missing or timezone-naive completion timestamps and tied
newest instants do not establish a unique latest success. Do not break ties by
run ID. If the latest execution cannot be established, say so; independently
validated dated history may still be available.

The latest successful execution is not necessarily the latest state whose
required data is still available and valid. Validate each source below. Report
accepted and rejected sources, selected run IDs, snapshot dates, completion
times, warnings, and missing fields. A later terminal success cannot recover
historical rows overwritten by another same-day attempt.

## Current asset membership and completeness

Before calling current accounts and positions a complete asset state:

1. Inspect the full `accounts_current` and `positions_current` tables, before
   filtering by run or activity. Require non-empty, unique canonical
   `account_key` and `position_key` values across each table, including inactive
   rows. Reject duplicate physical keys instead of silently deduplicating.
2. Require valid `is_active` flags on every row: native booleans or the exact
   strings `TRUE` and `FALSE`. Blanks, numeric 0/1, and other strings are invalid.
3. Every active account and position must carry the selected successful
   `run_id` in `last_seen_run_id`. Reject mixed or foreign active memberships,
   even when total row counts are unchanged. Never discard foreign-run rows to
   make a count pass.
4. Require active counts to equal that run's `accounts_count` and
   `positions_count`. Counts accept finite, non-negative integers as native
   numbers or trimmed decimal numeric strings (for example `2`, `2.0`, `2e0`).
   Reject missing/blank counts, booleans, negatives, fractional values, NaN,
   infinity, and locale-formatted strings such as `2,0`. Missing is not zero.
5. Require every active position's `account_key` to reference an account in
   the validated active account set. When combining current positions with
   independently validated history for the same run, require identical
   position-key membership.
6. Exclude `is_active = FALSE` rows from holdings and active counts. They retain
   their last observation's `last_seen_at` and `last_seen_run_id` when rewritten
   as inactive. An older inactive run ID alone is normal and does not invalidate
   a complete snapshot. Conversely, an unsuccessful inactivation can remove a
   previously held position while all remaining active IDs still match the
   prior run: the count check must reject this incomplete membership.

Only after these checks may `is_active = TRUE` rows be used as complete holdings.
If either table fails, the combined current asset state is unusable. Do not
present a filtered subset as a complete portfolio. Use the historical procedure
below, without requiring invalid current tables to pass first. Valid current
membership does not itself validate a daily aggregate or missing history.

## Historical fallback and independently usable aggregates

For each candidate business date, newest date first:

1. Require exactly one `portfolio_daily` row for the date and exactly one
   matching successful terminal `sync_runs` record, using the selection rules
   above. Require a valid `generated_at` whose Europe/Paris date matches
   `snapshot_date`; coverage and shared gross/liability/net-worth totals must
   agree with that terminal record. Totals must respect finite-number and blank
   semantics; only `COMPLETE` permits numeric liability-dependent totals.
2. Inspect all history rows for that date before selecting membership. Require
   non-empty, unique canonical `position_key` values and the exact
   `{snapshot_date}:{position_key}` history keys; reject duplicate physical
   keys, including duplicates carrying a different run ID.
3. Select only history rows for that date and `portfolio_daily.run_id`. Require
   their count to equal the run's valid `positions_count` and their
   `generated_at` to match the daily row. Distinct retained keys from earlier
   runs may remain on that date but are not members of this state. Never fill
   missing members using another run. Blank legacy history run IDs cannot
   establish membership.
4. If these checks pass, use only these historical rows for position detail.
   Otherwise mark that date's position detail unusable and examine an older
   date. If none passes, report the requested position data unavailable.

For example, successful A can retain valid EUR 150 history while interrupted
B has EUR 160 active current positions. Reject B's current data and use A's
EUR 150 history. If B also overwrites part of A's same-day history, A's terminal
success cannot reconstruct A: select an explicitly older valid date or report
position detail unavailable.

A fallback is always explicitly dated, even on the same business date: disclose
its run ID, snapshot date, completion time, warnings, and freshness limitation.
Separate it from the latest successful execution. When daily production is
expected, a selected state's completion time older than 48 hours is stale;
state that limitation and respect any stricter user freshness requirement.

Historical answers are limited to the columns actually stored in
`positions_history` or safely derivable from those validated rows. Account keys
are retained, but historical account balances, account names/types/institutions,
regions, native market values, and liability details are not. Do not enrich
history from invalid current rows, apply today's metadata retroactively, invent
missing fields, or reconstruct account balances by summing positions. Preserve
blank EUR values; any allocation derived from history covers only the known-EUR
subset and is not necessarily full portfolio allocation.

A daily row passing step 1 can still supply its stored aggregates when position
detail fails steps 2–3. Keep `portfolio_daily.gross_assets_eur` authoritative;
do not replace it with a position sum. Label an independently usable aggregate
with its own run and date, especially when position detail comes from an older
fallback. Unavailable detail does not automatically invalidate an independently
validated aggregate. Do not combine different states into one portfolio snapshot.

## Sequential-read limits

These are read-side interpretation checks, not transactions or locks. Sequential
Sheets reads can span concurrent writes, including writes whose failed telemetry
never arrives. Reject observed membership, count, key, or evidence changes;
repeat a full read after writes settle. If repeat reads show changed evidence,
do not combine them. Even identical repeated reads cannot prove an atomic
snapshot or rule out an unobserved concurrent change. Report unresolved
consistency limits instead of claiming transactional consistency.

The repository's test-only executable specification exercises these rules; it
is not a deployed consumer validator and does not automatically enforce them
inside ChatGPT. ChatGPT must obtain sufficient table data and apply the rules;
if retrieval cannot establish completeness, report the requested data unavailable.

## Synchronization statuses and warnings

- `SUCCESS`: all portfolio writes completed and no warning was generated.
- `SUCCESS_WITH_WARNINGS`: all intended writes completed, but coverage is
  incomplete or a monitoring threshold was crossed. Consumers still validate the
  available rows and apply the stated warnings.
- `FAILED`: synchronization did not produce a new valid portfolio state.
  Financial fields may be blank. Use prior data only where its required
  evidence and rows still pass validation.

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

`portfolio_daily.liability_coverage` in a validated daily state has three values:

- `COMPLETE`: the validated daily totals are authoritative for that state.
  Detailed liability rows require the separate validation below.
- `PARTIAL`: some liabilities may be known, but the set is not exhaustive.
  Current total liabilities and net worth are not authoritative and remain
  blank.
- `UNAVAILABLE`: no authoritative current liability collection is available.
  Current total liabilities and net worth remain blank.

Under `PARTIAL` or `UNAVAILABLE`, do not conclude that the user has no debt, do
not treat liabilities as zero, and do not equate gross assets with net worth.
Select the latest successful run with `COMPLETE` liability coverage separately
from the latest successful asset run. Apply the same unambiguous terminal and
parsed, timezone-aware completion selection rules. Inspect the full
`liabilities_current` table: require non-empty unique canonical `liability_key`
values, valid activity flags, active membership entirely matching that COMPLETE
run's `last_seen_run_id`, and an active count equal to its valid
`liabilities_count`. Use the same count representations as for assets. Retained
inactive rows are excluded from debt and counts; older observation IDs on those
rows are allowed. Check the finite outstanding amounts against the complete
run's liability total and require a consistent retained `last_seen_at` for
active details. Arithmetic consistency checks allow the exported prewrite
tolerance of `1e-8` EUR for floating-point rounding; copied daily/terminal values,
counts, membership, and authoritative zero evidence still require exact agreement.

Do not require these rows to match a newer `PARTIAL` or `UNAVAILABLE` asset run.
A later same-day asset synchronization can replace `portfolio_daily` without
invalidating independently proven last-known complete liabilities: that older
daily row is not required for detail validation. A partially rewritten table
from a failed `COMPLETE` attempt, including failed inactivation, fails the
membership or count checks. If details fail, report them unavailable. There is
no liability-history table from which to build replacement details; a validated
daily liability aggregate can still be reported for its own date.

An empty active liability set proves zero only with matching successful
`COMPLETE` terminal evidence, a valid zero `liabilities_count`, and numeric zero
`liabilities_eur`. Without that evidence an empty table means unavailable data.
Disclose the separate run ID, `completed_at`, and retained `last_seen_at` snapshot
date for last-known complete details. For zero rows, use a matching validated
daily row's `generated_at` if it survives; otherwise only the run completion
time is available and the exact liability snapshot date is unknown. Never
invent it from a run ID or label `started_at` as the snapshot timestamp.

Under newer `PARTIAL` or `UNAVAILABLE` coverage, current liabilities and net
worth remain unknown. Do not subtract older last-known complete liabilities
from newer gross assets and present the result as authoritative current net
worth. Last-known complete data always has separate provenance.

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

Join failure telemetry to written rows by exact `run_id` or `last_seen_run_id`,
never by timestamp proximity or execution ordering. A failure without a usable
source execution ID is reported only in n8n, so the absence of a `FAILED` row
does not prove success. Require the successful-run membership checks above.

The position kind is part of position identity because the same numeric asset ID
may exist in different upstream categories. Preserve category-aware IDs exactly.

Business dates use `YYYY-MM-DD` in the `Europe/Paris` timezone. Timestamps are
ISO 8601 with an explicit timezone offset. Parse timestamps as instants before
comparison; do not treat an ambiguous local timestamp or lexical row order as
chronological authority.

Treat `run_id` as an opaque equality key. Never sort it, parse a timestamp from
it, or reconstruct it from a business date.
