# MCP questions and observation interpretation

Use two explicitly separate modes. An independently authorized direct MCP read
answers a current question with the returned view and limitations. A validated
workbook observation supplies retained history and manual analysis. Neither
mode grants authority to combine live overview figures with older workbook
holdings into one complete observation. A workbook fallback must name its
provider, collection window, business date, successful run and limitations.

## Nine-action question/source matrix

| Action | Appropriate question and source | Required interpretation |
| --- | --- | --- |
| `get_me` | Who is connected? Direct authorized identity/preferences read | Preferences are display choices; identity does not determine portfolio ownership. Not scheduled ingestion. |
| `profiles` | Which explicit household profiles are available? Direct authorized read | Labels are not a cross-observation identity mapping. Use only explicit resource references. Not scheduled ingestion. |
| `accounts` | Which accounts and bank connections are represented? Direct MCP or one validated workbook observation | Full balance, EUR conversion and combined direct-owner value are distinct. Duplicate-looking accounts remain separate. No wrapper guessed from names. |
| `holdings` | What is held in each account? Exhausted MCP collection or validated history | Holding resource identity, native denomination, retrieval and valuation coverage are independent. Product identity does not merge holdings. |
| `get_portfolio_overview` | What are gross assets, Financial Assets, reported debt, net worth and official allocation? | Official figures have authority. Detail sums and custom classifications never replace them. Household/direct scope and currency must be explicit. |
| `get_budget_overview` | What does the returned budget period show? On-demand `/v3/budget` or direct MCP | Whole-household caller configuration is separate from portfolio ownership. Preserve partial periods, counts, unpriced amounts and uncertain history. Twelve-month averages retain denominator 12 and months-covered qualification. |
| `search_spending` | What aggregate matches this explicit user label? On-demand `/v3/spending-search` or direct MCP | Require a nonblank label. Preserve returned filter, direction, dates and unpriced counts. No invented transactions, label crawling or argument rewriting. |
| `goals` | What plans, targets and contributors are configured? On-demand `/v3/goals` or direct MCP | A complete response is an observation, not stable goal identity. Preserve currency and month precision. Plans do not prove progress, success, ownership or investment cashflows. |
| `simulate_compound_interest` | What would happen under user-confirmed hypothetical inputs? Direct on-demand capability only | Illustrative simulation. Starting capital, contributions, duration and assumptions must come from explicit user inputs; never derive them from portfolio or budget. Not called by the bridge or schedule. |

The scheduled MCP call set is overview once, accounts once, and paginated
holdings for every accepted account. It contains no analytics prompt, budget,
search, goals, identity/profile enumeration or simulation. Optional capability
failure cannot fail the portfolio route.

## Workbook acceptance

[The canonical workbook contract](google-sheets-schema.json) owns fields and
bindings. The executable reference is
[`app/mcp_consumer.py`](../finary-bridge/app/mcp_consumer.py). It accepts complete
physical row reads, checks duplicate keys before selecting membership, requires
one successful terminal for the observation/run, validates per-table expected
counts, reconstructs typed records and applies the production snapshot rules to
a complete current selection. Null counts mean unavailable/unwritten; zero
means validated empty membership. A later `FAILED` record is not a replacement
for the newest successful observation. Duplicate terminal evidence is invalid.

Current account/position rows carry their last actual observation, including
when retained inactive. Never relabel them with a later run. Historical holdings
retain observation-qualified keys, so two observations on the same Paris date,
including a source cutover, cannot overwrite each other. Historical fallback
never borrows later current account balances or metadata. Account balances are
not a retained account time series in this schema; fallback can retain official
figures and validated holding history without claiming complete historical
account detail. Retained positions still pass the same standalone monetary and
identity checks as current positions, including exact EUR equality and consistency
between holding identifiers, account keys and position keys. Missing historical
account metadata never disables those checks or authorizes borrowing later data.

Compare only compatible provider, API/workbook major versions, source contract,
view/scope, ownership basis, metric and currency. A missing or incompatible
baseline creates a **series break**. No percentage change alert is emitted from
an incompatible series. Unknown legacy provenance remains unknown; equal-looking
IDs, names, tickers, ISINs and row order are never crosswalk evidence.

A current source with an old last successful bank synchronization remains old.
A recently failed connection remains broken even when its entity update or
bridge ingestion is recent. Manual accounts have no bank failure solely because
they lack a connection. A successful run older than 48 hours is operationally
stale; report bank freshness separately. Sequential reads describe a collection
window, not an atomic upstream snapshot.

Reported debt is not verified loan detail. An `assets_only` overview with count
zero does not prove zero debt. A complete overview with unvalued liabilities is
not complete debt valuation. Even a complete zero-debt overview cannot clear
unverified loans. The current MCP writer never writes or inactivates loan rows.
Member amounts can be null and member net worth can be negative; ordinals are
unique only within the observation.

Official allocation and custom `AssetClass` analysis remain separate. An exact
enabled MCP override affects custom classification only. Deliberately carrying a
legacy override requires the migration helper's exact legacy/MCP pair, `VERIFIED`
state, dated review and evidence reference. Unresolved entries remain unapplied.
Native amount/currency evidence controls valuation completeness. Nullable EUR
projections require their own basis; account EUR evidence never converts the
overview. Store exact decimal strings as RAW text, including known zero.

Valuation change is not investment performance. Without separately validated
investment cashflows and an appropriate methodology, do not report investment
returns. Budget aggregates and planned contributions never enter manual
`cashflows`. Unknown budget history remains an explicit limitation: free-text
notes are not an accounting algorithm. Target currency can remain unknown and
floor/ceiling semantics must be preserved without unsupported variance math.
