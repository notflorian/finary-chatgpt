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
- the assistant must report the selected `run_id`, `completed_at`, status,
  warnings, and liability coverage when giving a portfolio-wide answer;
- unknown values remain unknown, and incomplete coverage must be disclosed;
- analysis is informational and must not trigger trading or external actions.

Keep the instructions focused on behavior. Put tab descriptions, key formats,
null semantics, coverage rules, and calculation definitions in the uploaded
knowledge file so the instruction field remains short and maintainable.

## How ChatGPT should read the workbook

For a portfolio-wide question, ChatGPT should:

1. read `sync_runs` and select the newest valid `completed_at` whose status is
   `SUCCESS` or `SUCCESS_WITH_WARNINGS`;
2. report warnings and reject a stale state older than the user's chosen
   freshness threshold (the operations default is 48 hours);
3. filter current tables to `is_active = TRUE` unless explaining retained past
   state;
4. use `portfolio_daily.gross_assets_eur` as the authoritative gross-assets
   total;
5. for the selected date, take `portfolio_daily.run_id`, require its matching
   successful `sync_runs` row, then select same-date history rows with that
   `run_id` and verify their count and unique position keys;
6. treat blank currency and numeric cells as unknown, never zero;
7. interpret `liabilities_eur` and `net_worth_eur` only when liability coverage
   is `COMPLETE`;
8. describe allocation figures as the known-EUR active-position subset when
   `PARTIAL_POSITION_EUR_COVERAGE` is present;
9. apply enabled manual targets and overrides according to their documented
   semantics;
10. distinguish valuation history from investment performance, especially when
   cashflows are incomplete.

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
- “List only active positions and explain whether their EUR coverage is
  complete.”
- “Compare current known-EUR allocation with enabled allocation targets and
  disclose the calculation denominator.”
- “Explain whether the available history is sufficient to calculate investment
  performance after external cashflows.”

A correct response should cite workbook tabs or rows, preserve blank/null
meaning, avoid adding positions to account balances, and avoid treating an empty
liability table as proof of zero liabilities.

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
