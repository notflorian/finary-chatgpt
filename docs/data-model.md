# Google Sheets data model

## Canonical contract

[google-sheets-schema.json](google-sheets-schema.json) is the generated current
workbook layout 1.0. The single field-level source is `current_workbook` in
[finary-mcp-contract.json](finary-mcp-contract.json), with leaf types from its
normalized MCP definitions. The generator also packages an identical schema.
It defines sheet order, ordered headers, keys, nullability, ownership and update
behavior directly. The initializer and consumer use this exact structure.

## Tables and ownership

The initializer creates these tables in order:

| Tables | Purpose |
| --- | --- |
| `README` | Current versions and semantic metadata, initialized once |
| `writer_control` | One operator-controlled writer ID, positive generation and PAUSED/ACTIVE state |
| `sync_runs` | One terminal record per execution, exact observation membership/counts and sanitized failures |
| `accounts_current`, `positions_current` | Physical current rows, including retained inactive rows |
| `positions_history`, `portfolio_daily` | Immutable accepted holdings and authoritative overview observations |
| `account_ownership`, `source_connections`, `position_rates` | Independent ownership, freshness and rate evidence |
| `official_allocation_categories`, `official_allocation_types` | Official allocation, independent of custom classification |
| `portfolio_members`, `observations` | Observation-local member figures, provenance and coverage |
| `source_warnings`, `unsupported_details` | Allowlisted diagnostics without upstream free text |
| `allocation_targets`, `asset_overrides`, `cashflows` | Manual inputs, never synchronization write targets |

Debt detail is unavailable and has no table. Reported overview liabilities,
net worth and debt valuation coverage remain independent of debt-detail availability.
Current accounts are not a historical account metadata store.

## Types and financial distinctions

Native amounts, quantities and rates are exact decimal strings, written as RAW
text. The project bounds are 24 integer digits and 64 fractional digits. No
JavaScript Number or Sheets numeric conversion is permitted for these fields.
Nullable fields are blank when unknown. Explicit empty-string updates clear old
values; zero and false remain known values. Integer counts use exact safe integers.

Native currency and verified EUR amounts each retain their evidence. Full account
value and directly owned value are different concepts. Buying price retains its
basis and is not cost basis. Official overview totals and official allocation
never derive their authority from sums of account/holding rows.

Manual target percentages are decimal fractions: `0.75` means 75%, with
`0 <= min_pct <= target_pct <= max_pct <= 1`. Manual cashflows use explicit EUR
amounts with signed contributions/withdrawals and paired internal transfers.
An enabled override uses exact MCP `source_asset_id` and changes custom asset
classification only. All manual rows require unique keys and typed literal values;
formulas are allowed only in notes. Names, tickers and equal numeric IDs do not prove identity.

## Observation membership and recovery

Daily/history keys include observation UUIDs, so multiple observations on one
Paris business date coexist. Native retries retain the same execution identity;
new full executions use a fresh UUID. A successful terminal is written only after
all required batches. Null counts mean unavailable/unwritten; zero means validated
empty membership. Missing current rows are inactivated only under sufficient
collection evidence, retaining their original observation and timestamps.

Every automated row must match exactly one valid stored terminal, including
partial rows from FAILED runs. Orphans and malformed rows invalidate the inventory.
The consumer validates physical keys, activity, counts, references and financial
semantics before treating current rows as complete. Accepted dated history can
supply fallback without later account metadata. Currency, scope, ownership, metric
and source-contract changes break series comparability. Collection time and bank
freshness remain distinct; a success older than 48 hours is operationally stale.
Sequential reads/writes are not transactional.

## Fresh installation

Use the [executable initializer and setup sequence](operations.md). It creates a
new blank workbook with current README metadata and a PAUSED writer control row.
This breaking layout rejects prior schemas and supplies no data conversion.
Existing operator data is not modified. See [consumer interpretation](chatgpt.md#reading-an-observation)
for accepted observations and limitations.
