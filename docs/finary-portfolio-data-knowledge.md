# Finary Portfolio Data workbook knowledge

This reference describes workbook layout 1.0, API 1.0 and source contract 1.0.0.
It does not replace the ChatGPT Project's behavioral Instructions or the user's
Personal Investment Policy. The canonical field contract is
[google-sheets-schema.json](google-sheets-schema.json); the executable reference
consumer is [mcp_consumer.py](../finary-bridge/app/mcp_consumer.py).

## Selecting the latest successful execution

Read complete tables, actual headers, current `README`, and singleton
`writer_control`. Reject incompatible layouts, missing evidence, duplicate keys
and conflicting terminals. Validate every automated row against its row schema
and exactly one matching terminal, including rows outside the selected observation
and partial rows associated with FAILED terminals. Orphan or malformed rows
invalidate the inventory; do not silently filter them away. Select the newest valid `completed_at` for `SUCCESS`
or `SUCCESS_WITH_WARNINGS`, interpreting ISO 8601 with an explicit timezone
offset. A later FAILED row never replaces a stored success. Tied completion
instants cannot establish an unambiguous latest state.

A run ID is an opaque UUID-bearing equality key. The observation UUID identifies
one collection. `sync_runs` supplies per-table expected counts; null means
unavailable/unwritten and zero means validated empty membership. Every selected
row must belong to that exact observation and run. Accepted `positions_history`
and `portfolio_daily` observations remain distinct even on the same business date.

Before using `accounts_current` or `positions_current` as complete, inspect all
physical rows, unique keys and valid activity flags. Active rows must match the
selected observation/run and expected counts. Inactive rows retain their last
actual observation identity and timestamps. A failed write can invalidate current
state; historical fallback must be independently validated and explicitly dated.
Never borrow later account balances or metadata to enrich older history.

## Authority and independent evidence

Official overview gross assets, financial assets, reported liabilities and net
worth are authoritative. Account and holding sums do not replace them. Official
allocation in `official_allocation_categories` and `official_allocation_types`
is independent of custom classification and manual targets.

`observations` retains scope, ownership basis, currency, collection window and
independent retrieval, valuation, semantic and freshness coverage.
`account_ownership`, `source_connections` and `position_rates` supply independent
qualified evidence. `portfolio_members` has observation-local ordinals, not
stable cross-observation identity. `source_warnings` and `unsupported_details`
explain supported limitations without raw provider messages.

Debt detail is unavailable and no debt-detail table exists. Overview liabilities
and debt valuation are separate: reported debt may be known while detailed loans
remain unavailable. Unknown is not zero, and zero unsupported-detail rows do not
prove the absence of undiscovered upstream assets.

Native amounts, quantities and rates are exact decimal text; blank is unknown,
not zero. Verified EUR values need explicit currency evidence, with no speculative
foreign-exchange conversion. Full and directly owned account values differ.
Buying price has its own basis and must not be treated as cost basis.

## Manual inputs and analytical limits

`allocation_targets`, `asset_overrides` and `cashflows` are operator-owned and
never synchronization write targets. Targets use decimal fractions and manual
cashflows use explicit EUR. Enabled overrides use exact MCP `source_asset_id`
without name, ticker or cross-provider matching. They affect custom classification
only; budget/search/goals never populate investment cashflows. Manual rows need
unique keys and typed literal values; formulas are permitted only in notes.
Allocation fractions obey `0 <= min_pct <= target_pct <= max_pct <= 1`.

Every exposure calculation must state its scope and denominator. Unknown
classification, currency or membership makes combined-cap certification
indeterminate. A zero subset percentage is not proof of zero actual exposure;
a zero denominator has no defined percentage. Valuation changes are not investment
returns without sufficiently complete external cashflows and a suitable method.

Currency, scope, ownership basis, metric and source-contract changes create
meaningful series breaks. A successful state older than 48 hours is operationally
stale; bank freshness and collection timestamps must be disclosed separately.
Sequential Sheets reads/writes are not atomic. A matching repeat read can help
spot changes but cannot establish a transaction. If full evidence is unavailable,
report qualified aggregates, dated fallback or unavailable detail explicitly.
