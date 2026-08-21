# n8n daily synchronization

Phase 5 provides the importable `Finary - Daily Sync` workflow at
`n8n/workflows/finary-daily-sync.json`. It was import-validated with self-hosted
n8n 2.35.5 and uses only built-in Manual Trigger, Schedule Trigger, HTTP
Request, Code, If, and Google Sheets nodes.

## Prerequisites and import

Before importing the workflow:

1. Create the `Finary Portfolio Data` workbook.
2. Create all ten sheets and their ordered headers from
   `docs/google-sheets-schema.json`.
3. Create a Google Sheets OAuth2 credential in n8n and grant its Google account
   access to the workbook.
4. Configure the n8n environment variables below.
5. Import `n8n/workflows/finary-daily-sync.json`.
6. Assign the same Google Sheets credential to each Google Sheets node. The
   exported workflow deliberately contains no credential identifier.
7. Run the Manual Trigger once and inspect the terminal `sync_runs` row.
8. Import `n8n/workflows/finary-error-handler.json`, assign its Google Sheets
   credential, publish it, and select it in the daily workflow Settings as the
   error workflow. Imported IDs are instance-specific, so this link is manual.
   Publishing this Error Trigger workflow creates no schedule or external
   endpoint.
9. Keep the daily workflow unpublished/inactive while verified liability
   coverage is unavailable. Activate its schedule only after a complete manual
   snapshot succeeds.

The workflow does not create, clear, reformat, or repair the workbook. A missing
sheet or shifted header aborts before portfolio writes.

## Configuration

| Environment variable | Required | Meaning |
| --- | --- | --- |
| `FINARY_GOOGLE_SHEET_ID` | Yes | Spreadsheet ID from the workbook URL |
| `FINARY_BRIDGE_URL` | No | Bridge base URL; defaults to `http://finary-bridge:8000` |
| `FINARY_SCHEMA_URL` | No | Canonical Phase 4 JSON URL; Compose defaults to `http://schema-server/google-sheets-schema.json` |
| `FINARY_BRIDGE_API_KEY` | No | Sent as `X-API-Key`; no value is embedded in the workflow |

For a bridge running directly on the same host, set `FINARY_BRIDGE_URL` to an
address reachable from the n8n process, such as `http://127.0.0.1:8000` for a
non-container n8n process. A container cannot use its own `127.0.0.1` to reach
the host.

The workflow timezone is `Europe/Paris`; the Schedule Trigger uses
`30 7 * * *`, so n8n handles daylight-saving transitions. Run IDs use
`YYYYMMDD-HHMMSS`. Business dates are derived from the snapshot's timezone-aware
`generated_at` in `Europe/Paris`.

Warning thresholds are centralized in the `Prepare Validated Rows` Code node:

- absolute day-over-day net-worth change greater than 20%;
- active account count change greater than 30%;
- active position count change greater than 30%.

## Schema-driven preflight

`docs/google-sheets-schema.json` remains the only schema source. Every run loads
it through `FINARY_SCHEMA_URL`, verifies schema version `1.0`, and derives the
Google Sheets resource-mapper schemas from its column definitions. The workflow
does not embed an independent header list.

Before any portfolio mutation, read-only preflight nodes read row 1 as data so
headers are observable even when a sheet has no data rows. The workflow compares
the exact ordered headers for `asset_overrides` and every managed write sheet,
checks the canonical unique keys, then constructs and validates all target rows
in memory. The Google Sheets write nodes perform their own schema check again at
each write boundary.

Every Google Sheets read node has n8n's `Execute Once` setting enabled. Chained
read nodes must not execute once per row returned by the preceding sheet: doing
so would multiply API calls as current and telemetry sheets grow, exhaust the
per-user Google Sheets quota, and make run duration depend on workbook size.

Every Google Sheets node has a bounded native retry policy: three total attempts
with five seconds between attempts. n8n 2.35.5 supports a fixed retry delay,
not native exponential backoff. Write nodes intentionally do not use `Execute
Once`, because all selected rows must be written. The daily workflow has a
300-second execution timeout.

The validation gate rejects unsupported or error responses, naive timestamps,
non-EUR schema 1.0 references, suspicious empty accounts or positions, missing
or duplicate IDs, broken account references, malformed category-aware position
keys, non-finite values, negative liabilities, inconsistent liability/net-worth
totals, impossible account/gross-asset relationships, ambiguous overrides,
duplicate target keys, header drift, and unexpected target columns.

## Write and idempotency behavior

Writes begin only after the full preparation succeeds and run in this order:

1. `accounts_current`, matched by `account_key`;
2. `positions_current`, matched by `position_key`;
3. `liabilities_current`, matched by `liability_key`, when rows exist;
4. `positions_history`, matched by `history_key`;
5. `portfolio_daily`, matched by `snapshot_date`;
6. `sync_runs`, matched by `run_id`, last.

All operations are append-or-update. Nothing is cleared or deleted. Records
missing from a complete successful snapshot are retained and marked
`is_active = FALSE`; their prior financial values and last-seen fields are not
replaced with zero. A known-empty complete liability collection can therefore
inactivate prior liabilities. An unavailable liability collection produces a
structured bridge error and performs no portfolio write or inactivation.

History keys are `{snapshot_date}:{position_key}`. A same-day rerun updates the
same history and daily rows; a later business date creates new rows. Because
all writes use deterministic keys, rerunning after a mid-write failure repairs
the completed prefix without duplicating it. Google Sheets has no transaction,
so a failed write can leave a partial prefix; successful telemetry is written
only after every portfolio write completes. Full failure diagnostics and
automated recovery remain Phase 6 work.

## Null, currency, and totals

JavaScript `null` is passed to Google Sheets with `allowEmptyValues` enabled and
RAW cell input. It becomes a blank cell. The workflow never uses zero or text
sentinels for unknown values and never performs truthy numeric coercion.

No FX conversion or display-field inference occurs in n8n. Position weights and
asset-class percentages use only active positions whose `market_value_eur` is
known. A position with an unknown EUR value has a blank weight. A zero known-EUR
denominator makes every percentage blank. Unknown-EUR positions cause
`SUCCESS_WITH_WARNINGS`; analytical totals describe only proven EUR coverage
and must not be interpreted as reconciliation to gross assets.

`gross_assets_eur`, `liabilities_eur`, and `net_worth_eur` are copied from the
validated Phase 3 snapshot. Positions are never added to accounts and never
replace the authoritative gross-assets value. The stable API does not expose
the upstream `is_collection` flag, so n8n can only apply a one-sided consistency
guard: authoritative gross assets cannot exceed the sum of known normalized
account values. It cannot reproduce the bridge's exact collection exclusion.
`financial_assets_eur` remains blank because no non-overlapping definition is
contract-backed.

Envelope totals use exact normalized `account_type` values only: `PEA`, `CTO`,
`ASSURANCE VIE`/`LIFE INSURANCE`, and `CASH`/`COMPTE COURANT`/`CURRENT ACCOUNT`.
No account-name or institution heuristic is used; unmatched groups remain
blank.

## Asset overrides and manual sheets

Only enabled `asset_overrides` rows are read. Matching precedence is exact
`source_asset_id`, normalized-uppercase ISIN, normalized-uppercase ticker, then
an NFKC-normalized, trimmed, whitespace-collapsed, case-normalized exact name.
No fuzzy matching occurs. Multiple matches at the highest applicable precedence
abort preparation. Overrides may change only asset class, subclass, and region;
identity and account association remain unchanged.

The workflow never writes `allocation_targets`, `asset_overrides`, `cashflows`,
or the workbook `README` sheet.

## Telemetry statuses

- `SUCCESS`: every portfolio write completed with no warning.
- `SUCCESS_WITH_WARNINGS`: writes completed, but partial known-EUR coverage or a
  centralized change threshold generated one or more warnings.
- `FAILED`: a sanitized bridge/schema failure was recorded without portfolio
  mutation. Null portfolio totals remain blank.

Validation errors raised after Google state is loaded stop the workflow before
the first portfolio write. Structured bridge failures write one sanitized
`FAILED` row through the main workflow and complete normally. Other uncaught
node failures are handled by `Finary - Error Handler`, which writes only to
`sync_runs`, never overwrites a terminal run ID, and never copies raw exception
text or stacks into Sheets. Monitoring and recovery are documented in
`docs/operations.md`.
