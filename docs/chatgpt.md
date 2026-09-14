# ChatGPT integration

For official MCP, follow the [nine-action source matrix](mcp-consumer.md). Direct
authorized reads answer current questions; validated workbook observations
provide retained history and manual analysis. Explicitly date any fallback and
never present a live overview plus stale workbook detail as one observation.
The supported workbook is layout 4.0. Validate its actual headers, README,
control and per-observation terminal membership with the production reference
consumer before interpretation.

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
- the workbook headers match schema `4.0`;
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
- dated historical fallback and reported overview liabilities must have
  separate provenance; missing details must not be invented or enriched from
  invalid current rows;
- unknown values remain unknown, and incomplete coverage must be disclosed;
- analysis is informational and must not trigger trading or external actions.

Keep the instructions focused on behavior. Put tab descriptions, key formats,
null semantics, coverage rules, and calculation definitions in the uploaded
knowledge file so the instruction field remains short and maintainable.

## How ChatGPT should read the workbook

Read the current [knowledge reference](finary-portfolio-data-knowledge.md) and
[MCP consumer rules](mcp-consumer.md). Use only full independently validated
observations with explicit business date, run/observation identity, completion
time and limitations. Missing rows or counts are not zero. Official totals and
allocation retain their authority even when detail is unavailable.

Debt detail is unavailable. Reported liabilities and net worth may still be
known from the official overview; retain their currency and debt valuation
qualifiers. Never infer debt detail or combine earlier liabilities with later
assets as an authoritative current total. Historical fallback never borrows
later current account metadata.

No connector retrieval makes sequential Sheets reads atomic. If complete tables,
headers or membership are unavailable, describe the limitation instead of
certifying a complete current portfolio. Update the uploaded knowledge reference
when the workbook contract changes; repository changes do not update it automatically.

## Connection and revocation boundaries

The n8n Google Sheets OAuth credential and the ChatGPT Google Drive connection
are independent. Removing ChatGPT access does not revoke the separate Google
OAuth credential stored in n8n or the independently authorized Finary connection.
Keep the workbook private. This integration does not authorize automated
purchases, sales, or transfers.
