# Official Finary MCP contract

The [machine-readable contract](finary-mcp-contract.json) is the field-level
source for normalized data and `current_workbook`. Generated models, workbook
schemas and the inactive workflow implement it. Application `1.0.0`, API `1.0`,
workbook `1.0` and source contract `1.0.0` have independent purposes. The source
version describes this project's interpretation, not an upstream Finary release
or negotiated MCP protocol revision.

## Schema and evidence layers

- `*_output` describes connector-declared payloads. An open object has no implied
  inner schema; a declared string does not prove a valid amount or date.
- `*_observed` describes structural evidence with conservative optionality.
  Project identity and parent requirements do not imply universal upstream
  requiredness or verified ownership/currency semantics.
- `holdings_page`, `snapshot_v1`, normalized types and workbook bindings are
  project-owned acceptance contracts, including cross-field semantic validation.
- `evidence` distinguishes connector declarations, observed/reported structure,
  public documentation, project decisions and synthetic defensive examples.
  Capability `support_status` describes evidence; `runtime_status` describes
  whether this bridge implements the action. Neither alone certifies all
  financial meanings, permissions or live availability.

Primary product context is the [Finary MCP page](https://finary.com/fr/mcp) and
[assistant setup guide](https://help.finary.com/fr/articles/16335735-utiliser-le-mcp-finary-avec-mon-assistant-ia-claude-chatgpt-perplexity-mistral).
The official resource is `https://public-api.finary.com/mcp`. Runtime discovery
checks required declarations; a public action count is not a capability allowlist.
The [synthetic manifest](../finary-bridge/tests/fixtures/finary-mcp/manifest.json)
uses invented data with independent expected outcomes. Synthetic cases verify
implementation, not upstream support. Fixed test dates are deterministic inputs.

## Capabilities

| Action | Bridge use | Evidence and limits |
| --- | --- | --- |
| `get_portfolio_overview` | Required snapshot overview | Explicit household/direct/gross-assets view; reported totals and allocation are authoritative |
| `accounts` | Snapshot account/owner/connection detail | Structural mappings; owner entries do not establish household stake |
| `holdings` | Paginated per-account snapshot detail | Supported resource types retain per-field ownership/unit qualifiers |
| `get_budget_overview` | `/v1/budget`, on demand | Declared and observed structure; history and target currency remain qualified |
| `search_spending` | `/v1/spending-search`, on demand | Declared aggregate search, explicit user label only; no independent semantic completeness claim |
| `goals` | `/v1/goals`, on demand | Plan variants and attributed month precision; no stable goal identity or progress |
| `get_me` | Not exposed | Reported open identity object; never a portfolio total |
| `profiles` | Not exposed | Reported open context array; labels do not establish ownership |
| `simulate_compound_interest` | Not exposed | Declared projection, unknown series-item shape; no ingestion use |

Scheduled collection calls overview once, accounts once and holdings for every
accepted account. It sends no analytics prompt and never calls optional tools,
identity/profile enumeration or simulation. Optional failures do not fail the
portfolio route. The supported MCP HTTP routes are `/v1/snapshot`, `/v1/budget`,
`/v1/spending-search` and `/v1/goals`; other API majors return 404.

## Transport and authorization

The native client owns SDK negotiation, catalog discovery, bounded tool results
and fixed errors. The adapter owns included-resource joins and normalization;
HTTP returns `McpSnapshotV1` and optional typed responses, never raw relationships
or reading notes. Source provenance is fixed to `finary_official_mcp`, with no
provider selection, fallback or field supplementation.

Local API-key authorization precedes client construction, state access and I/O.
Health and OpenAPI are local. Independent operator OAuth verifies the Clerk issuer
and allowlisted endpoints. Normal routes and schedules do not register a client,
open consent or bootstrap state. Query labels and invalid inputs are sanitized
in request errors and excluded from access logs. See
[OAuth operations](operations.md#independent-mcp-oauth) for consent, ownership,
protected persistence, renewal and revocation limits.

HTTP 200 alone is not success. Reject protocol errors, `isError`, malformed or
conflicting text/structured envelopes and unsupported views. Accept only an
unambiguous typed payload. Retry transient failures within bounded call and
collection deadlines; do not rewrite business arguments to cure schema or
authorization failures. `transport_policy` defines time/byte/page/record budgets
and fixed error messages. These are project bounds, not advertised server limits.

## Financial authority and money

Official gross assets, financial assets, reported liabilities and net worth retain
their own scope. Account balances, owner entries, holdings, member totals and
allocation sums never replace or repair them. Official allocation remains
separate from custom classes and exact manual overrides.

All overview/allocation/member amounts use the explicit view currency, including
nullable amounts. Native balance, full EUR value and directly owned EUR value
are distinct account concepts. Owner values apportion account value; shares can
exceed one and do not prove a household stake. Company look-through is unavailable.

Preserve native money/quantity/rate strings exactly within 24 integer and 64
fractional digits. Bounds are project policy, not a verified upstream maximum.
No floats, exponent syntax, truncation or rounding intervene. Exact decimal
comparison accepts equivalent spellings such as `0` and `0.00`; storage retains
the original spelling. Null/absent means unknown; zero is known. Malformed,
non-finite and out-of-bound values fail.

An EUR projection requires evidence. Overview/holding EUR projections require
explicit EUR denomination; no speculative FX is supported. A native account
balance may use its independently supplied `full_value_eur`, never its directly
owned value, as conversion evidence. Account EUR evidence never converts an
entire overview. `display_*` fields and retrieval timestamps prove neither EUR
nor price freshness. An unknown native amount has unknown EUR amount.

Buying price remains qualified by its currency and unit/total basis; it is not
cost basis. Do not multiply an already supplied total by quantity, infer a
right's amortization, add anticipated staking rewards or derive P&L/yield from
unverified units. Distinct holdings of one product remain distinct. Unsupported
ownership variants gain no mapping from these interpretation rules.

## Independent coverage

Retrieval, native valuation, debt valuation, debt detail, semantic confidence and
source freshness are separate dimensions. Native valuation is complete only when
every accepted row has the covered amount and currency; a complete empty
collection qualifies. EUR projection, quantity, cost and ownership remain separate.

| Overview view | Reported debt/net worth | Qualification |
| --- | --- | --- |
| Complete, zero unvalued debt | Preserve, including known zero | Reported debt valuation complete |
| Complete, positive unvalued debt count | Preserve | Debt understated/net worth overstated; valuation partial |
| Assets only | Unknown | No debt/net-worth completeness claim |

An assets-only zero count does not prove no debt. The implementation supplies no
debt-detail rows or debt table. The schema's empty debt representation requires
independently verified empty enumeration to qualify as COMPLETE; overview zero
alone is insufficient. The bridge retains debt detail as unavailable.

Supported holding resources may preserve explicitly UNVERIFIED ownership/units.
Unknown nonempty resource shapes produce partial detail and typed diagnostics,
not complete empty holdings. Protocol/malformed/pagination failures abort the
snapshot; they do not become an overview-only success. Explicitly unavailable
or unsupported detail may preserve an otherwise valid overview with warnings.
Only sufficient complete collection evidence permits current-row inactivation.

Collection start/end, generated time, entity update, last sync attempt and last
successful bank sync are independent. A recent attempt does not cure a broken
connection. Bank success older than 48 hours is stale. Manual accounts use
NOT_APPLICABLE; unresolved connections use UNKNOWN. Keep suspected duplicate
accounts rather than guessing identity. Export allowlisted diagnostics, never
free-text upstream errors or personal/authentication details.

## Identity and pagination

`identity` defines exact key templates. Encode UTF-8 bytes except ASCII letters,
digits and `-._~`, using uppercase percent escapes. Never trim, case-fold,
Unicode-normalize or numerically coerce identifiers. Escape `%` and `:` distinctly.
Account keys use the assets resource type; position keys include account,
holding type and holding ID, never product/ticker/name fallback.

Resolve included resources by `(type,id)`; ambiguous duplicates or conflicting
parents fail. Holdings must reference the requested assets account. Missing
optional enrichment stays null, with explicit ownership/connection evidence.
Member ordinals are unique only within an observation and imply no persistent
person identity. Warnings use unique `(code, entity_key)` pairs, including null;
unsupported diagnostics use `(account_key, holding_type, reason)` and require
an account in the same observation. Diagnostics never authorize inactivation.

Fetch every account's holdings, including zero holdings. Maintain a fixed limit,
contiguous offsets, stable totals, unique resource identities and consistent
terminal `has_more=false`. The schema's required pagination fields and bounded
budgets govern completion. Changed totals, missing pages, repeated identities,
conflicting parents and empty nonterminal pages fail. Relative links are
structural evidence only; pagination uses MCP calls, never arbitrary REST links.

## Optional reads

Budget/search accept `this_month`, `last_month`, `last_3_months`, `year_to_date`, or
paired inclusive dates. Explicit dates override period, must be ordered/calendar
valid and cannot end after today's Europe/Paris date. Preserve returned windows,
partial-period/day counts, history bounds and unpriced counts. Last three months
is trailing, not the previous calendar quarter.

Budget describes configured whole-household cashflows without portfolio ownership
scaling. Totals, recurring/variable splits, categories, monthly/profile/joint rows
and comparisons retain independent meanings. Null rate/average/detector values
are not zero. Monthly category averages divide by 12; months-covered evidence
qualifies the baseline. Target currency is unconfirmed: `should_reach=true` means
floor and false means ceiling, but neither certifies target achievement.
Unknown history means UNVERIFIED; contradictory source evidence remains
INCONSISTENT. Do not parse free-text notes into accounting rules or zero populated
amounts to repair a contradiction.

Search requires a nonblank user label substring and optional income/spending
direction. Preserve the returned filter and unpriced counts. Results are
aggregates, not transactions, a merchant directory or a wildcard crawl.
Neither budget nor search populates investment `cashflows`.

Goals preserve plan variants, currency, nullable amounts, contributors and
funding-account relationships. Months of emergency coverage are not money.
Plans add no assets; funding accounts may overlap. Names, order and creation time
are not stable goal IDs. Attributed month precision must not turn a represented
15th into a precise deadline. Do not infer progress, ownership or contributions.
Simulation is outside the bridge; external hypothetical questions require
confirmed inputs rather than values inferred from portfolio or budget data.

## Timestamp validation

The canonical `timestamp` definition applies to normalized responses, retained
workbook rows and supported source timestamps, including goal creation dates.
It requires a real Gregorian date in `YYYY-MM-DD` form (years 0001–9999), uppercase
`T`, and `HH:MM:SS` with hours 00–23 and minutes/seconds 00–59. An optional dot
fraction has 1–6 digits. The required timezone is uppercase `Z` or `±HH:MM`
(hours 00–23, minutes 00–59); signed zero offsets denote the same instant as UTC.

Accepted strings are preserved, including all microseconds. Python and the writer
compare complete instants across offsets; millisecond rounding must not create
completion ties or hide invalid collection ordering. Calendar validity, collection
windows, completion/freshness rules and Europe/Paris business dates remain
independent checks. Nullable unknown timestamps remain null in the API and blank
in Sheets; required timestamps cannot be blank.

Compact dates, comma fractions, omitted seconds, hour 24, leap seconds, excess
fractional precision, whitespace, trailing data and non-string timestamps are
rejected without normalization or rollover. This tightens parser-specific
acceptance of the previously underspecified date-time contract; it adds no
upstream compatibility. Ordinary service output is unchanged. Application/source
`1.0.0` and API/workbook `1.0` remain unchanged for this validation correction.
Retained unsupported encodings fail validation; they are never rewritten or
silently truncated. Adopt matching bridge/reader and generated writer/schema
artifacts using the [operator procedure](operations.md#generated-artifact-adoption).

## Workbook and compatibility

`current_workbook` directly defines ordered sheets, headers, keys, types,
nullability, ownership, update behavior and README metadata. The generated
canonical and packaged schemas are identical. The
[fresh initializer](operations.md#fresh-workbook-initialization) creates PAUSED
control and empty tables. It does not convert or relabel an existing workbook.

Writer/consumer validation checks structure as well as versions. Each retained
automated row must pass its schema and match exactly one stored terminal with
the same run/provider, including valid FAILED partial rows. Orphans block reads
and writes. Manual sheets are read-only to synchronization and require unique
keys, typed literals, formulas only in notes and ordered allocation fractions.
Overrides use exact MCP source identities and affect custom classification only.

Validate every prepared batch before the first portfolio write. Current missing
rows become inactive only with sufficient evidence and keep their observation
identity/timestamps; already-inactive rows are not rewritten. Accepted daily and
holding history remains immutable across distinct same-day observations. Empty
branches continue once without fabricated rows. Terminal success follows required
writes and identity/control rechecks; a lost response cannot replace stored
success. Valid FAILED membership enables recovery, while hard-loss orphans require
operator review. Sequential Sheets operations are not atomic.

The consumer can return independently validated dated fallback without later
account metadata. Compare series only with compatible known currency, ownership
basis, scope, metric and source-contract semantics. Changes or missing baseline
dimensions create a series break. Valuation changes are not investment returns.
The `ambiguities` register records ongoing uncertainty and conservative behavior;
implementation or a synthetic pass does not upgrade that evidence.
