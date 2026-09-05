# ChatGPT integration

## Recommended setup

Use a private ChatGPT **Project** as the portfolio-analysis workspace. In the
product surface verified for this repository, the custom-GPT editor/runtime did
not expose the Google Drive connection needed to read the live workbook. A
Project did. This is a scoped product limitation and may vary by ChatGPT plan,
workspace policy, region, or future product changes; confirm the available
connectors in your own account.

The Project design keeps two concerns separate:

- **Instructions** define assistant behavior and the authority of your personal
  investment policy;
- **sources** provide the private workbook and durable reference material.

Google Drive files added to a Project are retrieved on demand rather than
copied into this repository. Do not export a static workbook copy when the live
Drive source is available.

## Prerequisites

Before connecting ChatGPT:

- the daily synchronization has produced at least one `SUCCESS` or
  `SUCCESS_WITH_WARNINGS` row;
- the workbook headers match schema `2.1`;
- the workbook contains no Finary credentials, cookies, tokens, or raw payloads;
- Google sharing is restricted to the intended user or workspace;
- you have a personal investment policy suitable for use as the primary
  behavioral reference.

The n8n Google Sheets OAuth credential and the ChatGPT Google Drive connection
are independent. Revoking one must not silently revoke or validate the other.

## Create the Project

1. Create a private ChatGPT Project for portfolio analysis.
2. Add Project Instructions that require every portfolio recommendation to be
   checked against your personal investment policy.
3. Upload your personal investment policy as a Project source.
4. Upload
   [`finary-portfolio-data-knowledge.md`](finary-portfolio-data-knowledge.md) as
   a Project source. This file teaches ChatGPT the workbook's stable semantics;
   it does not replace behavioral Instructions.
5. Connect Google Drive to ChatGPT, using the minimum account scope that allows
   the Project to read the workbook.
6. Add the exact private **Finary Portfolio Data** spreadsheet link as a Project
   source.
7. Ask the Project to read the workbook `README` tab and the knowledge file
   before interpreting financial tables.

Do not add the bridge URL, an n8n webhook, Finary credentials, Google OAuth
tokens, or a public spreadsheet link to the Project.

## Suggested Project Instructions

The instructions can be written in the user's preferred language. They should,
at minimum, establish these behavioral rules:

- the personal investment policy is the primary authority for portfolio
  analysis and recommendations;
- the assistant must check allowed instruments, exclusions, limits, wrappers,
  extra-financial criteria, fees, liquidity, replication, concentration,
  rebalancing, and sale rules before recommending an action;
- a conflicting request must be described as non-compliant rather than
  optimized around the policy;
- missing policy guidance must be stated, not invented;
- the live **Finary Portfolio Data** workbook is the source for portfolio facts;
- workbook semantics come from `finary-portfolio-data-knowledge.md` and the
  workbook `README` tab;
- the assistant must validate complete current-table membership before using
  current holdings, and report accepted/rejected sources, selected `run_id`,
  snapshot date, `completed_at`, warnings, and liability coverage;
- dated historical fallback and last-known complete liabilities must have
  separate provenance; missing details must not be invented or enriched from
  invalid current rows;
- unknown values remain unknown, and incomplete coverage must be disclosed;
- analysis is informational and must not trigger trading or external actions.

Keep the instructions focused on behavior. Put tab descriptions, key formats,
null semantics, coverage rules, and calculation definitions in the uploaded
knowledge file so the instruction field remains short and maintainable.

## How ChatGPT should read the workbook

Use the complete [knowledge-reference procedure](finary-portfolio-data-knowledge.md#selecting-the-latest-successful-execution).
For a portfolio-wide question, ChatGPT should:

1. Retrieve full relevant tables, including all physical rows and pages. Select
   the latest unambiguous `SUCCESS` or `SUCCESS_WITH_WARNINGS` using parsed,
   timezone-aware `completed_at`. Require exactly one terminal record per run
   across statuses. Reject missing evidence, conflicting duplicates and tied
   newest instants; `run_id` is an opaque equality key. Absence of `FAILED` is
   not proof of success.
2. Before filtering current accounts or positions, validate non-empty unique
   canonical keys and valid activity flags across both tables. Require every
   active `last_seen_run_id` to match the selected run, with exact
   `accounts_count` and `positions_count`. Counts must be finite non-negative
   integers as numbers or decimal numeric strings; missing counts are not zero.
   Flags accept booleans or exact `TRUE`/`FALSE`. Reject extra, missing,
   duplicate, mixed or foreign active rows. Validate position-account links;
   if using same-run history too, require identical position-key sets.
3. Exclude inactive rows from holdings and active counts. Their older
   `last_seen_run_id` is their last observation, not their last write. Detect
   incomplete prior membership caused by failed inactivation using counts.
4. If current data fails, use only independently validated history: one daily
   row and matching successful terminal record, consistent coverage/totals,
   canonical unique history keys, matching date/run membership and generated
   timestamp, and valid `positions_count`. No reconstruction from mixed rows.
   Try older valid dates explicitly; otherwise report details unavailable.
5. Disclose the selected source, date, run, completion time and warnings,
   distinguishing the latest successful execution from available valid data.
   State the fallback freshness limitation (stale after 48 hours by default)
   and respect any stricter user threshold. Limit historical detail to stored
   fields or safe derivations: no invalid-current enrichment, invented account
   metadata/regions/liabilities, or account balances reconstructed from positions.
6. Use validated `portfolio_daily.gross_assets_eur` as authoritative. A daily
   aggregate passing its own evidence checks may remain usable without position
   detail; report its separate run/date if it differs from the detail fallback.
7. Validate liability details independently against the latest successful
   `COMPLETE` run: full-table unique keys and flags, matching active run IDs and
   `liabilities_count`, and consistent amounts and observation time. Allow
   retained inactive rows and newer incomplete asset runs, including same-day
   daily replacement. Failed complete writes invalidate details; there is no
   liability-history fallback. Zero requires successful COMPLETE evidence plus
   valid zero count and total. Disclose separate liability provenance; never
   combine older liabilities and newer assets as authoritative current net worth.
8. Treat blank currency and numeric cells as unknown, never zero. Describe
   allocation as the known-EUR subset when coverage is partial. Use enabled
   manual targets and overrides according to the documented semantics, without
   applying today's metadata retroactively to historical positions.
9. Distinguish valuation changes from investment performance when cashflows
   are incomplete. Reject observed inconsistencies or changes during sequential
   reads and repeat full reads after writes settle; these checks do not create
   a transactional snapshot, even when repeated reads agree.

The repository provides a test-only executable specification, not a deployed
consumer validator. It does not automatically enforce these checks inside
ChatGPT. If retrieval cannot supply enough data to validate completeness, report
the requested data unavailable.

With incomplete liability coverage, liabilities and net worth are unknown, not
zero.

The workbook can support summaries, calculations, allocation comparisons, and
descriptive explanations. It does not establish personalized suitability by
itself and does not authorize automated purchases, sales, or transfers.

## Useful first queries

Start with interpretation checks before requesting investment analysis:

- “Identify the latest valid synchronization and report its run ID, completion
  time, status, warnings, and liability coverage.”
- “State gross assets, liabilities, and net worth. Explain every unknown value
  without replacing it with zero.”
- “Validate current account and position membership, then list accepted
  holdings or an explicitly dated historical fallback and explain EUR coverage.”
- “Compare current known-EUR allocation with enabled allocation targets and
  disclose the calculation denominator.”
- “Explain whether the available history is sufficient to calculate investment
  performance after external cashflows.”

A correct response should cite workbook tabs or rows, preserve blank/null
meaning, avoid adding positions to account balances, and avoid treating an empty
liability table as proof of zero liabilities.

## Adopt the corrected consumer instructions

The workbook `README` is initialized from the canonical schema; portfolio
synchronization does not automatically rewrite it. Follow the
[operator adoption checklist](operations.md#consumer-validation-adoption)
to update the changed README entries and replace the uploaded
`finary-portfolio-data-knowledge.md` reference. Update existing Project reading
instructions that merely filter active rows. A local repository update alone
does not change the live workbook or an already uploaded Project source.

## Access revocation

To remove ChatGPT access:

1. remove the workbook source from the Project;
2. disconnect or revoke the ChatGPT Google Drive connection;
3. confirm a new Project query can no longer retrieve the workbook;
4. review Google account connection activity and workbook sharing.

This does not revoke the separate Google OAuth credential stored in n8n. Revoke
that credential independently when synchronization access must also stop.

If the Project is shared with another person, that person may see retrieved
portfolio content according to ChatGPT and Google access controls. Keep the
Project private unless that disclosure is intentional.
