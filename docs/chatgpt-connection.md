# ChatGPT connection runbook

## Status and prerequisites

This is the canonical Phase 13 runbook. Phase 13 acceptance is complete: the
user authorized Google Drive in ChatGPT, located the private canonical workbook,
read its `README`, and passed the complete semantic acceptance matrix. This
record is intentionally structural and contains no financial values,
identifiers, account names, or conversation content.

Before authorization, require all of the following:

- issue #18 is closed and PR #29 is merged;
- the single production `Finary - Daily Sync` workflow remains published on
  `30 7 * * *` in `Europe/Paris`;
- the canonical private **Finary Portfolio Data** workbook has schema `2.0` and
  exactly the ten tabs in `google-sheets-schema.json`;
- `sync_runs` has a `SUCCESS` or `SUCCESS_WITH_WARNINGS` row completed within
  the last 48 hours; choose the newest `completed_at`, not the last physical
  row;
- the workbook `README` contains every canonical `readme_entries` rule.

Stop and follow `operations.md` if the production state is stale or unhealthy.

## Architecture and authorization boundary

```text
Finary -> finary-bridge -> n8n -> private normalized Google workbook
                                      |
                                      v
                      user-authorized Google Drive app -> ChatGPT
```

ChatGPT reads only the normalized workbook boundary. Its Google authorization
is created through ChatGPT and is independent of the Google Sheets OAuth
credential stored by n8n. Never export or reuse n8n access/refresh tokens,
client secrets, credential records, or `N8N_ENCRYPTION_KEY`. Disconnecting
ChatGPT must not revoke n8n, alter the workbook, or stop the schedule.

For ChatGPT Pro, OpenAI's current Google Drive sync setup asks for permission
to see and download all files in the authorized Drive account. This is broader
than per-workbook authorization, so do not claim technical per-file least
privilege. Use the narrowest scope the product actually offers, keep the
workbook private, and intentionally query only **Finary Portfolio Data**.
Unrelated Drive files remain outside this application's intended data boundary.
A dedicated Google identity is an optional user security decision, not an
automatic setup step.

Official product references:

- [Google Drive app with sync — self-service setup](https://help.openai.com/en/articles/10948259-google-drive-app-with-sync-self-service-setup)
- [Google app for ChatGPT — data controls FAQ](https://help.openai.com/en/articles/10408842-google-app-for-chatgpt-data-controls-faq)
- [Apps in ChatGPT](https://help.openai.com/en/articles/11487775-connectors-in-chatgpt)
- [Projects in ChatGPT](https://help.openai.com/en/articles/10169521-projects-in-chatgpt)

## Current product-surface decision: use a Project

As observed on 2026-08-22, the custom-GPT editor/runtime available to this
personal ChatGPT account does not expose the connected Google Drive app to the
custom GPT. Therefore a custom GPT cannot currently combine this project's
reusable investment instructions with live access to **Finary Portfolio Data**
on the verified product surface.

This is a scoped observation, not a universal statement about every ChatGPT
plan or workspace. OpenAI documents Apps as a possible GPT capability, but
availability depends on plan, workspace settings, permissions, region, and
product surface. Do not switch back to the custom-GPT route unless Google Drive
access is explicitly available there and the complete semantic acceptance
matrix is rerun.

The supported configuration for this repository is a private ChatGPT Project.
Projects support project-specific instructions, uploaded reference files, and
Google Drive file or folder links as project sources. OpenAI currently states
that Google Drive content added within a Project is not synced in advance;
ChatGPT searches and accesses it on demand. The live workbook must therefore
remain a linked Google Drive source, not an uploaded static workbook copy.

## Configure the Project and select the workbook

The exact labels may vary by ChatGPT plan and UI version. Perform these actions
semantically rather than relying on a fixed screenshot:

1. Create a private ChatGPT Project for the investment assistant. Do not use a
   custom GPT for the current configuration.
2. Put the behavioral prompt and investment-policy priority in the Project
   Instructions.
3. Add `docs/finary-portfolio-data-knowledge.md` and the separate Personal
   Investment Policy as Project reference files. The technical file is
   reference material for the workbook contract, not current portfolio state.
4. In ChatGPT settings, open the Apps or connected-apps area and select Google
   Drive.
5. Connect the user's Google account through ChatGPT's own OAuth flow. Review
   the displayed scope and accept only the minimum currently supported scope.
6. In the Project's sources area, add the exact private **Finary Portfolio
   Data** Google Drive link. Do not upload or export a static copy, copy anything
   from n8n, change workbook sharing, or record the Drive ID in this repository.
7. In a new Project chat, locate that linked workbook. Reject backup, obsolete
   v1, test, and exported copies. Use title, schema `2.0`, ten-tab structure,
   and recent valid telemetry to confirm the canonical file.
8. Instruct ChatGPT to consult **Finary Portfolio Data — ChatGPT knowledge
   reference**, then read the live workbook `README` sheet before interpreting
   any financial table. Use only this workbook for the acceptance run.
9. Run the complete representative acceptance matrix below inside the Project.
   Until it passes, record the Project configuration as pending rather than
   extending the earlier generic ChatGPT acceptance claim to this new surface.

## Workbook interpretation contract

ChatGPT must apply these rules on every relevant answer:

- “current” account and position rows have `is_active = TRUE`;
- a blank cell is unknown/unavailable, never zero;
- `gross_assets_eur` from the newest valid daily state is authoritative;
- position values are analytical components and must not be added to account
  balances or substituted for gross assets;
- allocation uses active positions with known EUR values and may cover only
  that subset;
- `liability_coverage` permits `COMPLETE`, `PARTIAL`, and `UNAVAILABLE`;
- only `COMPLETE` makes current liability totals, current liability rows, and
  net worth authoritative;
- under `PARTIAL` or `UNAVAILABLE`, retained `liabilities_current` rows are at
  most the last-known complete liability state, not current liabilities;
- the latest valid synchronization is the newest `completed_at` whose status
  is `SUCCESS` or `SUCCESS_WITH_WARNINGS`; later failures do not advance it;
- state older than 48 hours is stale when production should be running;
- related current/daily rows should match that valid run context;
- valuation or composition change is not investment performance unless
  external cashflows are complete enough to separate contributions and
  withdrawals.

## Representative acceptance questions

Prefix every query with: **Read the workbook README sheet before interpreting
financial tables. Use only the canonical Finary Portfolio Data workbook.**
Record only PASS or FAIL—never answers, values, names, identifiers, or full
conversation content.

| Test | Ask | PASS requires |
| --- | --- | --- |
| A — latest success | What is the latest successful portfolio synchronization? | Newest valid `completed_at` across both success statuses; later `FAILED` ignored; warning status mentioned. |
| B — accounts | Show my current accounts. | `accounts_current`, active rows only, blanks preserved, source IDs omitted unless requested. |
| C — gross assets | What are my current gross assets? | Latest valid `portfolio_daily.gross_assets_eur`; no account-plus-position sum or position-total substitution. |
| D — allocation | Show my current allocation by asset class. | Active known-EUR positions only; partial coverage explicitly qualified, including `PARTIAL_POSITION_EUR_COVERAGE`. |
| E — liabilities | Do I currently have any debts? | Incomplete coverage yields “not authoritative,” never “no debt” from an empty sheet. |
| F — net worth | What is my current net worth? | `PARTIAL`/`UNAVAILABLE` yields “cannot determine,” never gross assets minus assumed zero. |
| G — nulls | What does a deliberately blank normalized numeric field mean? | Unknown/unavailable, not zero or proof that none exists. |
| H — positions | Which positions are currently held? | `positions_current` with `is_active = TRUE`; inactive retained rows excluded. |
| I — history | How has my portfolio changed over time? | Uses daily/history data; calls changes valuation/composition, not performance without complete cashflows. |
| J — targets | Compare current allocation with `allocation_targets`. | Descriptive drift only, known-EUR limitation stated, no automatic buy/sell orders. |

Also test this synthetic interpretation without adding a live row: if the latest
daily coverage is `UNAVAILABLE` while `liabilities_current` has older rows from
a `COMPLETE` snapshot, those rows are last-known complete records, not
authoritative current liabilities.

## Prohibited interpretations and source boundary

Fail acceptance if ChatGPT treats an empty liability sheet as no debt, blank as
zero, gross assets as a sum of accounts and positions, partial positions as the
full portfolio, the last physical telemetry row as the latest success, a
valuation change as investment return, or target drift as an automatic trade.

Do not provide ChatGPT with `.env` files, expanded Compose configuration, n8n
database or credential exports, execution payloads, encryption keys, Finary
credentials, MFA/TOTP material, Clerk cookies/session IDs, bearer tokens,
organization/member IDs, raw Finary payloads, or unrestricted bridge/n8n logs.
No custom MCP, plugin, proxy, webhook, public URL, service-account bridge, or
duplicate sync layer is part of this architecture.

## Revocation and reconnection

To remove Project-level use first remove the Google Drive link from the
Project's sources or delete the private Project. To remove ChatGPT's underlying
Google access, disconnect Google Drive from ChatGPT's Apps/connected-apps
settings. If desired, also revoke the ChatGPT/OpenAI grant in the Google
account's third-party access controls. These actions do not change the source
workbook.

Do not revoke or edit the n8n Google Sheets credential. Confirm n8n remains
healthy, the workflow stays published, and no workbook data changed. A full
disconnect/reconnect independence test is optional because it is a separate
authorization lifecycle operation. To reconnect, repeat ChatGPT's Google OAuth
flow, re-add the workbook link to the Project, read `README`, and rerun at least
test A.

## Troubleshooting

- Workbook not found: confirm the correct Google identity, private file access,
  Google Drive connection, linked Project source, exact title, schema `2.0`,
  and ten tabs. Project use is on-demand and does not pre-sync Drive content.
  Do not use a backup or upload a static workbook copy.
- Data appears stale: derive the newest valid `completed_at` from `sync_runs`.
  If it is over 48 hours old, stop current-state interpretation and use the
  production recovery steps in `operations.md`.
- Newer failed run exists: report it separately; do not replace the last valid
  state or advance freshness.
- Conflicting sheet timestamps: prefer rows tied to the latest valid `run_id`
  and disclose any mixed-run limitation rather than silently combining them.
- Wrong null, liability, allocation, or performance interpretation: reread the
  workbook `README`, then rerun the failed acceptance query.

## Sanitized acceptance evidence

Repository and production preflight statuses actually observed:

```text
PHASE_12_DEPENDENCIES_PASS
PRODUCTION_SCHEDULE_ACTIVE
LATEST_VALID_SYNC_FRESH
CANONICAL_WORKBOOK_FOUND
WORKBOOK_SCHEMA_2_0_PASS
WORKBOOK_PRIVATE_PASS
README_READABLE
README_CONTRACT_RECONCILED
ACCESS_REVOCATION_DOCUMENTED
```

The following ChatGPT-product statuses were confirmed by the user through the
actual ChatGPT connection:

```text
GOOGLE_CONNECTION_AUTHORIZED=PASS
CANONICAL_WORKBOOK_FOUND=PASS
README_READABLE=PASS
CURRENT_ACCOUNTS_SEMANTICS=PASS
GROSS_ASSETS_SEMANTICS=PASS
KNOWN_EUR_ALLOCATION_SEMANTICS=PASS
LIABILITY_COVERAGE_SEMANTICS=PASS
NET_WORTH_NULL_SEMANTICS=PASS
NULL_HANDLING_SEMANTICS=PASS
LAST_SUCCESS_SEMANTICS=PASS
CURRENT_POSITIONS_SEMANTICS=PASS
HISTORY_SEMANTICS=PASS
TARGET_COMPARISON_SEMANTICS=PASS
ACTUAL_DISCONNECT_RECONNECT_TEST=PASS
```

The ChatGPT authorization is independent of n8n's credential. The
disconnect/reconnect check preserved the production synchronization boundary;
no n8n credential, Finary authentication state, workbook sharing setting, or
production schedule was changed. Close issue #19 through the accepted Phase 13
pull request after review and merge.
