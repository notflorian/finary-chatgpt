# Official Finary MCP integration contract

**Decision status: planned, contract version 1.0.0, inspected 2026-09-11.**
This document and the [machine-readable contract](finary-mcp-contract.json)
prepare API schema **3.0** at **`GET /v3/snapshot`** and workbook schema **3.0**.
They do not implement a client, authorization, normalization, route, writer or
migration engine. The implemented application remains 1.1.0, `/v2/snapshot`
remains canonical with API 2.0, and the active
[workbook contract](google-sheets-schema.json) remains 2.1. `/v1` and `/v2`
retain their existing behavior.

## Reading the artifacts

The JSON is the proposed contract's field-level authority. Its capability
registry points to reusable Draft 2020-12 `$defs`; normalized fields carry
`x-field` authority, grain, unit, currency and absence annotations. The workbook
section is a **migration delta**, referencing those types instead of maintaining
a competing active workbook schema. At implementation, the coordinated revision
must move workbook columns into the canonical workbook contract.

The source contract version identifies this project's interpretation, not a
Finary release or negotiated MCP protocol revision.

Schema layers have different meanings:

- `*_output` describes the assistant connector's declared payload types and
  required/optional fields. Open objects remain open. A declared string does not
  itself prove a valid amount or date.
- `*_observed` records inspected fields with conservative optionality/nullability.
  Identity and parent requirements are project acceptance rules, not claims that
  a field is universally required upstream.
- `holdings_page`, `snapshot_v3` and decimal schemas are project-owned acceptance
  contracts. The JSON's semantic rules additionally constrain relationships,
  cross-field currency, collection windows and evidence.
- The [fixture manifest](../finary-bridge/tests/fixtures/finary-mcp/manifest.json)
  links synthetic bases and defensive mutations to actions, schemas, evidence,
  quality and expected failures. Nothing was constructed by saving and redacting
  live responses. Synthetic cases never establish source support.

The [offline tests](../finary-bridge/tests/test_finary_mcp_contract.py) validate
schemas and examples, then check relationships and migration invariants. They
are an executable contract oracle, not proof of future runtime behavior.

## Evidence and limits

The [product page](https://finary.com/fr/mcp) describes a read-only connector and
lists eight actions. On the inspection date, the connected catalog exposed
**nine**, adding `search_spending`. The
[official guide](https://help.finary.com/fr/articles/16335735-utiliser-le-mcp-finary-avec-mon-assistant-ia-claude-chatgpt-perplexity-mistral)
provides assistant setup at `https://public-api.finary.com/mcp`. These pages are
context; discovered declarations and inspected response structures control this
contract. A marketing count is not a capability allowlist.

The [roadmap investigation](https://github.com/notflorian/finary-chatgpt/issues/85)
and [contract issue](https://github.com/notflorian/finary-chatgpt/issues/86)
record seven successful actions and forced holdings pagination using `limit=1`
and increasing offsets. This task re-inspected all nine declarations, read
accounts and overview once, read one holdings page with `limit=1`, and read one
budget response to establish its view field names. Only structural summaries
were retained. Earlier pagination evidence is historical, not a new complete
portfolio traversal.

| Action | Response evidence | Planned role |
| --- | --- | --- |
| `get_me` | Historical success; declared open data object | Optional connection identity; no identity/email export |
| `profiles` | Historical success; declared open data array | Optional structured ownership context, never ownership by name |
| `accounts` | Current resource/owner/connection structure | Full account and direct-owner detail |
| `holdings` | Current single security page; historical other types and pagination | Per-account typed holding resources |
| `get_portfolio_overview` | Current explicit view, totals, allocation, members | Authoritative overview |
| `get_budget_overview` | Current view fields; historical semantic contradiction | Optional cashflow read with quality limitation |
| `goals` | Historical success; declared plan variants | Optional plans, no measured progress |
| `search_spending` | Declaration only; not invoked | Explicit user label aggregate |
| `simulate_compound_interest` | Declaration only; not invoked | Explicit user projection only |

Nonempty loans, company/joint scenarios, non-EUR holdings and all advertised
holding types have **not** been verified. Historical observed types are listed
in `pagination.observed_types`; existence does not verify every valuation field.
The current wrapper supplies `content`, `structuredContent` and `isError`.
Neither this wrapper nor successful invocation proves the server's native wire
schema, protocol revision, transport negotiation or standalone OAuth lifecycle.

## Provider and authorization boundaries

The existing private `FinaryClient` interface continues to authenticate and
return its `FinaryRaw*` collections to the existing snapshot service. Its
account-balance authority, numeric collection identities, `holdings_account_id`
relationships and Clerk restart state remain **legacy provider semantics**.
`PortfolioSnapshotV2` still requires complete liabilities to equal the detailed
liability sum; these rules must not be reused as the MCP overview definition.

The planned MCP adapter owns transport, catalog discovery, authentication,
typed action inputs, result decoding, included-resource joins, pagination and
sanitized error translation. Its service returns only `snapshot_v3` to HTTP.
No raw resources, notes, transport envelopes or authentication material enter
n8n. Optional services use separate typed outputs and cannot become portfolio
prerequisites.

Freeze exactly one provider and contract version before each collection/run.
There is no mixed-provider observation, fallback, field supplementation or
implicit switch. Future `/v3` requires explicit MCP selection and rejects a
configuration mismatch before constructing a client. It must neither initialize
the private adapter nor require private email/password/MFA. Legacy routes remain
pinned to their current provider and initialize it only when called. Bridge API
key validation precedes either provider; `/health` remains metadata-only.

Standalone authorization is a verification gate for the
[client implementation](https://github.com/notflorian/finary-chatgpt/issues/87).
Earlier unauthenticated GET probes returned 403 without `WWW-Authenticate`; the
cause is unknown. This neither proves OAuth absent nor specifies discovery,
registration, grants, scopes, redirects or token lifetimes. Verify actual SDK
negotiation, discovery, consent, refresh rotation, restart and revocation before
claiming support. Bootstrap belongs to an operator command, never a scheduled
read or HTTP route. Do not extract assistant-managed credentials. Any verified
minimum OAuth restart state uses its own protected store, separate from Clerk.

## Value authority, ownership and currency

The overview is authoritative for its **reported** totals and official
allocation. Accept only explicitly supplied `scope=household`,
`ownership=direct`, `metric=gross_assets`; missing or different values fail with
`MCP_UNSUPPORTED_VIEW`. No defaults establish this view.

Keep gross assets, official Financial Assets, reported liabilities and reported
net worth distinct. Financial Assets includes savings, stocks/funds, crypto,
fonds euros and precious metals; it excludes checking, real estate, startups,
crowdlending, other assets and debt. `preferred_wealth_metric` changes display
preference only. Never reconstruct, replace, average or correct any official
total from account, holding, member or allocation sums.

Preserve `allocation_direct` as category rows and category/holding-type rows,
including unfamiliar identifiers. Custom `AssetClass`, exact source-specific
overrides and known-EUR position weights remain separate analyses with their
own population. They cannot change official allocation or its denominator.

An account's native balance and full EUR value describe the **full account**.
`total_owned_value_eur` combines explicit direct owners, not necessarily the
household's stake. Owner values apportion that value; they are not additional
assets. Ownership shares are fractions, and their sum may exceed one. Company
look-through is unavailable. Profile/member labels are not stable identities.
Generic account types cannot identify PEA, CTO, assurance-vie or tax wrappers;
missing wrapper metadata stays unknown.

The downstream decision is **native-value storage with nullable EUR projections**.
Overview monetary groups preserve `view.currency`; their EUR projection is
populated only for EUR. EUR account fields never imply an exchange rate for a
foreign overview. A native account balance may carry its explicitly supplied
full EUR conversion; its direct-owner EUR value is a different grain. Holding
current value and buying price retain independent denomination evidence. Do not
infer cost basis from buying price or infer ownership from quantity.

Ingestion uses bounded decimal strings parsed directly to decimal arithmetic,
with no binary float intermediate. Project bounds are 24 integer and 18
fractional digits; malformed strings, booleans, blanks, exponents, non-finite or
oversized values fail without rounding/coercion. Missing and null remain
unknown; zero remains known. New workbook decimal columns are exact **TEXT**,
written RAW, with explicit clearing for null. Legacy numeric columns retain
legacy values and are not reused for MCP numbers. Simulation's declared numeric
inputs/outputs are a separate approximate utility, never ingestion evidence.

Fractions, percentages, quantities, months and amounts have separate units.
`annual_yield_percent` is an annual percentage. `annual_yield` and fee-ratio
scales remain unverified until type-specific evidence establishes them. Preserve
these source decimals with qualified units; do not compute a yield, fee or cost
from an unverified scale.

## Independent coverage and freshness

The proposed API separates account retrieval, holding retrieval, debt-detail
retrieval, account/holding/debt valuation, overview quality, detail semantic
confidence and source freshness. Sequential calls form a collection window,
not an atomic upstream snapshot. Provenance records provider/version, explicit
view/currency, collection start/end, generated time and nullable upstream as-of.
Each observation has a fresh UUID; a successful writer run binds that observation
and each table's expected membership/counts.

| Overview source | Reported debt/net worth | Overview quality | Debt valuation |
| --- | --- | --- | --- |
| `complete`, unvalued count 0 | Preserve, including genuine zero debt | `REPORTED_COMPLETE` | `COMPLETE` for the reported view |
| `complete`, count > 0 | Preserve qualified figures; debt understated, net worth overstated | `REPORTED_UNVALUED_DEBT` | `PARTIAL` |
| `assets_only` | Unknown/null; source omits fields | `ASSETS_ONLY` | `UNAVAILABLE` |

A zero count under `assets_only` can itself be unavailable and never proves no
debt. A complete zero-debt overview needs no fabricated loan row. Conversely,
no overview authorizes clearing an unknown loan collection. Contract 1.0.0 has
**no nonempty debt-detail mapping**. Its empty detail representation can become
`COMPLETE` only with independently verified empty enumeration, supported detail
semantics and compatible complete account/holding retrieval; the overview alone
is insufficient. Until that evidence exists, debt detail remains unavailable.
Member debt can be null and member net worth negative; names/ordinals cannot
identify a member across observations.

Explicitly unavailable detail can permit a valid overview with warnings and an
empty corresponding write set. A failed page, malformed envelope, protocol
failure or invalid snapshot instead aborts before any portfolio writes. Complete
retrieval alone is not complete valuation. Only complete compatible retrieval
can inactivate absent accounts/positions; debt detail has its independent gate.
Consumers retain and date previous compatible detail separately, never attach
it to a new run as if freshly observed.

Keep ingestion time, entity update time, last sync attempt and successful bank
sync separate. Preserve source connection status and `last_successful_sync_at`;
a recent `last_sync_at` does not prove success. A successful bank sync older than
48 hours is stale under the project policy. Manual accounts have no bank-sync
freshness (`NOT_APPLICABLE`); an unresolved connection is `UNKNOWN`, not manual.
Retain suspected duplicate accounts. Export allowlisted warning codes and
entity references, never raw source error messages or reading notes.

## Identity and collection boundaries

Exact key templates and encoding are in `identity`. MCP keys use `mcp:` and
legacy `finary:` keys remain unchanged. Escape UTF-8 bytes with uppercase percent
encoding except ASCII letters/digits/`-._~`; `%` and `:` must be escaped. Reject
empty/whitespace/control IDs, never trim, numerically coerce or Unicode-normalize
them. Escaping is injective, including `a:b` versus `a%3Ab`. Equal IDs across
providers establish no equivalence.

Account identity includes resource type `assets`. Holding identity includes
**holding resource type and holding ID**, plus the account in the position key;
it never uses the underlying product ID. Two holdings of one product stay two
positions. Resolve included resources by `(type,id)`. The verified account path
is institution connection → included connection → institution. The holding
parent is `relationships.asset.data`. Missing optional enrichment leaves null;
account connection state distinguishes no connection from unresolved enrichment,
and ownership evidence distinguishes absent owners from explicit entries.
A conflicting parent or ambiguous included resource fails validation.

Holdings requires an account ID returned by accounts, defaults to limit 100 and
offset 0, and advertises max limit 1000. Fetch every account including empty ones.
Use fixed limits, contiguous offsets, stable totals, unique identities and a
consistent final `has_more=false`; enforce bounded call/page/record/time budgets.
Changed totals, repeats, missing pages, conflicting parents or unknown nonempty
types cannot produce `COMPLETE` evidence. Typed unsupported-detail counts retain
the account/type/reason without raw resource blobs. Partial pages do not authorize missing
position inactivation. Relative pagination links are evidence only: continue
through the MCP action, never private REST requests.

HTTP 200 is insufficient for tool success. Reject protocol errors, `isError`,
ambiguous/conflicting payload representations, malformed structures and
unsupported views with fixed sanitized failures. Retry only transient failures
within the contract budgets. Do not rewrite business arguments to fix provider
or authorization failures. The optional analytics `prompt` is not portfolio
data and is omitted from all scheduled calls.

## Optional capabilities

Budget and spending search accept `this_month` (default), `last_month`,
`last_3_months` and `year_to_date`, or paired inclusive explicit dates.
`last_3_months` is trailing, not the previous calendar quarter. Explicit dates
override period, must be valid, ordered, and cannot end in the future using
Europe/Paris's current date. Preserve actual returned dates, partial-period/day
counts, history bounds and unpriced counts; do not substitute requested labels.

Budget is caller-configured **whole-household cashflows**, without portfolio
ownership scaling. Preserve totals, recurring/variable splits, categories,
monthly rows, profile/joint rows and comparisons independently. Null rate,
average or detector output is not zero. Monthly category averages divide by 12;
`monthly_average_months_covered` qualifies the baseline. Targets have unconfirmed
currency; `should_reach=true` means floor and false means ceiling. No target
variance is certified before currency compatibility is established.

Historical evidence reports null history bounds and a note claiming no
transactions despite populated counts/amounts. Preserve this as attributed
`INCONSISTENT` evidence; null bounds alone imply `UNVERIFIED`. Do not zero or
discard amounts, certify a historical trend, or parse arbitrary English notes
into an accounting rule. The current bounded view check does not independently
re-establish the historical note contradiction.

Search requires an explicit nonblank user label substring, optionally filtered
to spending or income. It returns label-matching totals/counts, not transactions,
a merchant directory or complete shopping history. Preserve the returned trimmed
filter and unpriced count. Neither budget nor search populates investment
`cashflows` automatically.

Goals preserve plan variants, their own currency, nullable amounts, contributors
and funding-account relationships. Months of emergency coverage are not money.
Funding accounts can overlap; plans add no assets. No stable goal ID is exposed:
use a versioned whole-response read, not persistent identity from name, order or
`created_at`. The [goal issue](https://github.com/notflorian/finary-chatgpt/issues/93)
records month selection represented by day 15; attribute that precision until
verified and never call it a precise deadline. Do not infer progress, ownership,
contributions or simulation inputs from account balances.

Simulation remains explicit and on demand with user-confirmed capital, duration
and annual-rate inputs. It is never run as an ingestion prerequisite. Its series
items are declared unknown; defensive fixtures do not invent their schema.

## Migration, acceptance and rollback

The JSON defines normalized table/field mappings for the
[workbook revision](https://github.com/notflorian/finary-chatgpt/issues/90).
Keep the existing ten-sheet order and append ownership, connection, rate,
authoritative allocation, member, observation, warning, unsupported-detail and
migration/control tables.
Use typed columns, not raw JSON cells. Existing current/history/daily tables gain
explicit v3 columns; legacy values, keys and semantics remain intact. Optional
budget/search/goals persistence is outside this portfolio migration.

Same-day cutover requires a different identity: existing daily rows are keyed by
Paris date, and position history by date plus position key. New MCP daily/history
keys include observation UUID and the MCP namespace. Preserve both observations
on the cutover date. Same-payload retries reuse the observation/run keys; a fresh
collection gets a new UUID. Terminal membership selects each observation; a
partially written later run is never accepted as successful history.

Legacy provenance backfill uses a side table and only established evidence.
Unknown historical scope/ownership remains unknown; age does not establish an
MCP view. Preserve manual allocation targets, overrides and cashflows exactly.
Legacy overrides never apply to MCP IDs automatically. An unresolved crosswalk
stays unapplied; a deliberate mapping requires audited source evidence or
explicit operator verification. Even verified crosswalks do not rewrite old
keys or prove financial comparability.

The ordered migration plan in JSON requires inventory, backups, a separate
shadow workbook, dry-run validation, draining/disabling the old writer and its
error handlers, preserving legacy/manual data, applying the versioned delta,
checking counts/keys/values/manual digests, installing writer control, and
validating a candidate run before operator activation. A migration ledger binds
source/destination identity, versions and plan digest. Repeated identical plans
are idempotent; conflicting/partial states require validated recovery rather
than duplicate columns or rows. Writer control is a precondition, not a
replacement for operational exclusion of old executions. One active
writer/provider owns each workbook.

Acceptance requires preserved legacy/manual content, unapplied unresolved
mappings, retained same-day observations, correct native/null values, single
writer exclusion, valid terminal membership and disclosed series breaks.
Rollback drains MCP, preserves the entire new workbook and manual changes, and
resumes the legacy writer only against a compatible 2.1 workbook after deliberate
manual-change reconciliation. Never point a legacy writer at 3.0 or discard new
observations as part of rollback.

Compare histories only when provider, source contract, scope, ownership,
currency, metric definition and valuation quality are compatible. Unknown
legacy dimensions prevent a claim of comparability. Disclose changes as series
breaks and reset change alerts; collection/freshness differences qualify even
compatible comparisons. Valuation changes are not investment performance
without sufficient investment cashflow evidence.

## Remaining implementation gates

The machine-readable `ambiguities` register gives evidence, affected fields,
conservative behavior, impact and resolution criteria for ownership wording,
budget history, standalone OAuth, unobserved shapes, holding units, cross-provider
identity, goal precision, target currency and unknown objects. Open OAuth or loan
questions do not block shipping this contract; they block claiming the affected
runtime capability.

Client/authentication, detail normalization, v3 HTTP exposure, canonical workbook
migration, n8n writing, optional endpoints, consumer guidance and end-to-end
operator acceptance remain in the linked
[roadmap](https://github.com/notflorian/finary-chatgpt/issues/85).
No workflow activation, release, deployment or production migration is part of
this contract delivery.
