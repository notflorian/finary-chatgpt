# ChatGPT connection and reading workflow

Use the private workbook for retained observations and manual analysis. Direct
Finary MCP questions use a separate authorized connection for current questions;
a live overview plus older workbook holdings is not one complete observation.

## Connect the workbook

First complete [manual synchronization and readback](operations.md#consumer-readback-verification).
Keep Google sharing limited to your intended account/workspace. Finary OAuth in
the bridge, Google OAuth in n8n and ChatGPT's Google Drive connection are three
separate authorizations; changing one does not verify or revoke the others.

1. In ChatGPT, connect Google Drive using the connection/plugin controls available
   to your account and workspace. In ChatGPT Work, install Google Drive from
   Plugins and select it with `@Google Drive` in the task. See the
   [official connection guidance](https://learn.chatgpt.com/docs/get-started-with-work#add-plugins-for-more-context-and-better-outputs).
   Availability and permissions depend on the account; this repository does not
   assert that every plan or custom-GPT surface exposes the same controls.
2. Create a private portfolio Project or dedicated conversation. Add the exact
   workbook link and [portfolio knowledge reference](finary-portfolio-data-knowledge.md).
   If using a Project, keep the reference with its sources and the behavioral
   rules below in its Instructions. Confirm that ChatGPT can read the actual
   README and full tables, not merely a search preview.
3. Add your own investment policy if you want policy-based analysis. Keep it
   separate from the workbook semantics and tell ChatGPT which policy applies.
4. Ask for a read-only first analysis with the source/run/observation identity,
   business date, completion time, coverage, warnings and freshness disclosed.

If full workbook access is unavailable, provide a complete private export and
its export date. Treat it as a dated snapshot, never an automatically refreshed
source. A connection or uploaded guide does not install the Python reference
consumer in ChatGPT. Use the operator's offline readback command for executable
validation; do not claim that a language-model reading has run that code.

Never add Finary state, tokens, n8n credentials, a public workbook link or a bridge
endpoint as Project sources. Keep financial exports outside the repository.

## Suggested instructions

> Use the designated private workbook and its knowledge reference for portfolio
> facts. Read complete tables and validate observation membership before claiming
> current completeness. Disclose the selected run, observation, business date,
> completion time, coverage and warnings. Preserve unknown values and independent
> currency/ownership/freshness evidence. Date historical fallback and never enrich
> it with later account metadata or live MCP results. Check analysis against my
> stated investment policy; identify missing or conflicting policy requirements.
> Explain uncertainty and sources. Do not execute trades, transfers or external
> writes.

## Reading an observation

The [knowledge reference](finary-portfolio-data-knowledge.md) is self-contained
for interpretation. The [canonical schema](google-sheets-schema.json) owns exact
fields and [the production consumer](../finary-bridge/app/mcp_consumer.py) implements
validation. Workbook/API versions are `1.0`; source contract is `1.0.0`.

Validate complete physical headers, README, singleton writer control, unique
keys, typed manual inputs and every automated row before selecting any candidate.
Each automated row must match exactly one stored terminal with the same run and
official provider. Orphan/malformed rows invalidate the inventory, including rows
outside the selected observation. Valid FAILED partial rows may remain, but never
supply completed-observation evidence.

Choose the newest independently validated SUCCESS or SUCCESS_WITH_WARNINGS.
A later failure does not replace it. Null expected counts mean unavailable;
zero means validated empty membership. Active current rows must match the exact
observation/run and counts. Accepted history can support explicitly dated fallback
without later account metadata; current account balances are not historical
account evidence. If required tables are truncated or unavailable, report the
limitation instead of certifying completeness.

Official overview totals and official allocation remain independent of detail
sums and custom asset classes. Debt detail is unavailable even when reported
liabilities and net worth are known. Currency, ownership basis, scope, metric and
source-contract compatibility govern series comparisons. No percentage change is
meaningful across a series break. Missing baseline dimensions also create breaks.
A successful state older than 48 hours is stale; bank freshness is separate.
Sequential Sheets reads/writes are not atomic.

## Direct MCP questions

The bridge supports optional budget, explicit-label spending search and goals
through `/v1/budget`, `/v1/spending-search` and `/v1/goals`. They are independent
reads, outside workbook synchronization. Budget/search describe configured
household cashflows, not investment cashflows or transaction-level history.
Goals describe plans, not measured progress or additional assets.

The external connector may declare `get_me`, `profiles` and compound-interest
simulation; this bridge does not expose them. Simulation requires separately
confirmed hypothetical inputs, never parameters inferred from the workbook.
Declared capability, successful retrieval and verified financial semantics are
different evidence. See the [capability contract](finary-mcp-contract.md#capabilities).

Update the uploaded knowledge reference when the installed contract changes.
Repository edits do not update ChatGPT sources automatically.
