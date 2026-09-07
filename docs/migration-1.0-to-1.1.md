# Migrate from 1.0.0 to 1.1.0

This operator runbook upgrades an existing `v1.0.0` Compose installation and its
existing workbook. Follow it in order during a maintenance window, after the
`v1.1.0` tag has been published. It is not an automatic migration and no command
here should be run against production as part of a code review or CI.

The baseline is the actual `v1.0.0` release, commit
`5ad2cf1ddbf7a4104160eb59a0456377f68d2213`. If you already adopted intermediate
fixes from `main`, inspect the current state and skip only steps demonstrably
completed; never add a duplicate column or invent missing historical membership.

## What changes

| Area | Required action |
| --- | --- |
| Bridge application | Rebuild for `1.1.0`; `/v2/snapshot` stays on API schema `2.0` |
| Workbook | Upgrade schema `2.0` to `2.1` by appending `positions_history.run_id`; update seven README rules |
| n8n workflows | Adopt both new inactive exports; rebind every Google credential and the error workflow |
| Error correlation | Add a local **n8n API** credential to **Fetch Source Execution** |
| Container configuration | Recreate all three services; n8n needs `NODE_FUNCTION_ALLOW_BUILTIN=crypto` |
| Finary session | Stop every old writer first; preserve the existing session volume and format `1` JSON |
| ChatGPT | Replace the knowledge reference and update workbook-reading instructions |

The tab order and all existing headers remain unchanged. The only added column
is the final history column. New run IDs are opaque
`n8n-run:{execution_id}:{uuid_v4}` strings; retain old timestamp-shaped and
`n8n-execution` IDs unchanged. API clients using a closed field allowlist must
accept the additive `coverage.position_collections` field.

The n8n and schema-server image pins are unchanged from `v1.0.0`; use the pins
in this release's Compose file. No separate n8n database-version upgrade is
introduced by this release. Custom deployments must check their own image and
database compatibility rather than assuming the stock baseline.

## 1. Record the installation and stop new work

Run commands from the existing installation directory. Keep the same Compose
project name, `.env`, volume identities, and any explicitly used `-p` or
`--env-file` options throughout. A different directory/project name can create
empty volumes instead of reusing your n8n data and credentials.

```bash
git status --short
git rev-parse HEAD
docker compose ps
docker compose images
```

Stop if tracked local changes conflict with the upgrade; preserve and reconcile
them explicitly. Do not reset, automatically stash, or overwrite them. Record
the repository revision, image identities, daily/error workflow IDs, workbook
ID, and last verified successful run in private operator notes. Never include
credentials or financial values in a GitHub issue or release log.

In n8n:

1. Unpublish **Finary - Daily Sync** and stop all new manual executions.
2. Finish or cancel every running, waiting, queued, or resumable saved daily
   execution and its error handler. Resolve any native retry of an already
   finalized terminal write before upgrading.
3. Confirm nothing can resume against the workbook. Do not carry pinned node
   data, saved-data retries, or queued old error deliveries into the new setup.
4. Stop other writers, including old bootstrap commands and bridge processes
   outside Compose. Do not run old and new session-store implementations together.

## 2. Make a consistent recovery checkpoint

After executions have drained, stop the stack cleanly:

```bash
docker compose stop
```

Back up the stopped `n8n_data` volume using your platform's supported volume
backup procedure, preserve the exact `N8N_ENCRYPTION_KEY` separately in protected
storage, and make an access-controlled copy/export of the complete workbook.
Include the manual tabs and the initialized README. Record the common cutoff
and verify that you can restore the backup before proceeding.

Keep `finary_session_data` in place but **exclude it from backups**. Do not read
or copy its secrets. A restore requires a fresh human Finary bootstrap. Do not
copy a running SQLite database, rotate the encryption key, use `down -v`, prune
volumes, or delete either session JSON or its stable `.lock` sibling. See
[backup and restore](operations.md#backup-and-restore).

## 3. Select the release and check configuration

With a clean checkout and a published release:

```bash
git fetch origin --tags
git switch --detach v1.1.0
git rev-parse HEAD
git diff v1.0.0 v1.1.0 -- .env.example docker-compose.yml
docker compose config --quiet
```

Compare the selected commit with the published tag. Stop on any fetch, checkout,
or configuration error. Preserve `.env`; do not copy `.env.example` over it.

Verify locally without printing secret values:

- the workbook ID, existing encryption key, localhost bindings, timezone, and
  named-volume mappings are unchanged;
- `FINARY_BRIDGE_API_KEY`, when enabled, has the same value in bridge and n8n.
  Both snapshot routes now enforce `X-API-Key`; external local consumers must
  send it as well. `/health` remains unauthenticated;
- n8n receives `NODE_FUNCTION_ALLOW_BUILTIN=crypto` and
  `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`, as in the release Compose file;
- the existing bridge session path still points into its bridge-only local
  volume. All writers must share the coordinated lock protocol. The stable
  sidecar is initialized by the new implementation; do not create it manually.

Do not print full `docker compose config` output in shared logs: interpolated
configuration can contain secrets. `--quiet` is sufficient for validation.

## 4. Migrate the existing workbook while synchronization is stopped

Use `docs/google-sheets-schema.json` from the selected release as the authority.
Do not recreate the workbook or replace populated tabs with empty templates.

1. In `positions_history`, append `run_id` immediately after `cost_basis_eur`:
   column **R**, cell **R1**, in an unmodified schema `2.0` workbook. If this
   header already exists in the correct final position, do not add it again.
   Stop if custom columns or unexpected headers make the target ambiguous.
2. Leave all legacy cells in that new column blank. Do not infer membership
   from date, timestamps, row position, or retained terminal records.
3. In the workbook `README` tab, replace only the `value` and `description` of
   these seven existing keys from the release's `readme_entries`:
   `current_state_rule`, `history_rule`, `gross_assets_rule`,
   `failed_snapshot_rule`, `liability_rule`, `last_known_liability_rule`, and
   `last_success_rule`. Preserve other entries and all portfolio/manual rows.
4. Verify every tab's ordered headers against the schema. Preserve historical
   rows, inactive current rows, and the manual `allocation_targets`,
   `asset_overrides`, and `cashflows` tabs.

These read-only commands display the expected history headers and README values:

```bash
jq -r '.sheets.positions_history.columns | map(.name) | @tsv' \
  docs/google-sheets-schema.json
jq -r '.readme_entries[] | [.key, .value, .description] | @tsv' \
  docs/google-sheets-schema.json
```

The second command lists all README entries for reference; update only the
seven named keys. Portfolio synchronization never rewrites this initialized tab.
The schema version is `2.1`, but snapshot and `sync_runs.schema_version` remain
`2.0`. Do not change old telemetry to `2.1`.

## 5. Rebuild and recreate the stack

```bash
docker compose pull n8n schema-server
docker compose build finary-bridge
docker compose up -d --force-recreate
docker compose ps
curl --fail http://127.0.0.1:8000/health
```

Stop at any failed command. Adjust only the health URL port if your existing
installation deliberately uses a non-default bridge host port. Expect:

```json
{"status":"ok","service":"finary-bridge","version":"1.1.0"}
```

Recreation applies the n8n environment and refreshes the schema-server's mounted
JSON as well as the bridge image. A restart of an old container or an import of
workflow JSON alone does neither. Confirm the daily workflow is still unpublished.

Existing version `1` session JSON remains readable; a valid session does not
require MFA solely because of this upgrade. If the session is absent, expired,
or rejected, use the [interactive bootstrap command](../README.md#4-bootstrap-the-finary-session)
from this release. It verifies a fresh sign-in before publishing its replacement.
Do not pre-clear a usable session. Restart the bridge after replacement for
immediate adoption:

```bash
docker compose restart finary-bridge
```

Verify a snapshot without printing the body or placing an API key on the command
line. This operator check contacts Finary; it is not a credential-free test:

```bash
docker compose exec -T finary-bridge python - <<'PY'
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

headers = {}
api_key = os.environ.get("FINARY_BRIDGE_API_KEY", "")
if api_key:
    headers["X-API-Key"] = api_key
request = Request("http://127.0.0.1:8000/v2/snapshot", headers=headers)
try:
    with urlopen(request, timeout=300) as response:
        print(f"Snapshot HTTP {response.status}")
except HTTPError as error:
    raise SystemExit(f"Snapshot check failed: HTTP {error.code}") from None
except (URLError, TimeoutError):
    raise SystemExit("Snapshot check failed: connection unavailable or timed out") from None
PY
```

Require HTTP 200. Health success alone does not verify session validity. If any
step fails, keep synchronization unpublished and follow
[authentication recovery](operations.md#finary-authentication-failure); do not
clear session state or blindly repeat a failed replacement.

## 6. Adopt both workflows and restore runtime bindings

Import the release's **inactive** exports into n8n:

- `n8n/workflows/finary-error-handler.json`;
- `n8n/workflows/finary-daily-sync.json`.

Use the complete generated JSON exports, not individual `.js` source files.
Updating repository files does not update workflows already stored in n8n.
If imports create new workflow IDs, retain the old workflows unpublished and
use only the newly configured pair. Never leave two schedules published.

Before running anything:

1. Assign the existing Google Sheets OAuth2 credential to **every** Sheets node
   in both workflows, including reads, preflight, and failure branches. Preserve
   **Execute Once** for reads; row-write nodes must process every prepared row.
2. Create or verify an **n8n API** credential for this same local instance, base
   URL `http://127.0.0.1:5678/api/v1`, with permission to read daily execution data
   (`execution:read` where scopes are available). Bind it to **Fetch Source
   Execution** in the error handler. Keep the key only in n8n's credential store,
   never `.env`, workflow exports, Sheets, or ChatGPT.
3. Keep failed execution data enabled (`saveDataErrorExecution = all`), finite
   execution timeouts, bounded retries, and the release's environment expressions.
4. Publish the new error handler, then select its actual workflow ID in the
   daily workflow's **Error Workflow** setting. Keep daily sync unpublished.
5. Check that no pinned/saved old node output will be used. Every acceptance run
   must start as a full new execution with a fresh identity.

The handler needs original execution data to correlate failures. A missing
credential or pruned source data fails closed and may leave no `FAILED` workbook
row; absence of failure telemetry is not proof of success. Follow
[identity adoption](operations.md#adopting-restore-safe-run-identities), including
a controlled failure against an isolated test workbook with synthetic data,
before production scheduling. Never inject a failure into production holdings.

## 7. Update ChatGPT consumers

Replace the uploaded `docs/finary-portfolio-data-knowledge.md` source in every
consuming Project with the release copy; remove obsolete duplicate references.
Update custom instructions using the
[workbook-reading procedure](chatgpt.md#how-chatgpt-should-read-the-workbook).

Consumers must validate full physical current tables, membership, counts, and
account references, not merely filter `is_active = TRUE` or a desired run ID.
Historical fallback needs independently validated date/run/count evidence, and
liabilities need independent latest-successful-COMPLETE provenance. Disclose
fallback dates and staleness. The reference consumer in the tests is not an
automatic runtime enforcement layer inside ChatGPT.

## 8. Verify new runs, then resume the schedule

Start one full manual daily execution and wait for it and any error handler to
finish. Apply all [first-run checks](operations.md#first-run-verification):

- exactly one terminal record for its new opaque `run_id`, with `SUCCESS` or
  `SUCCESS_WITH_WARNINGS`, bridge version `1.1.0`, and API schema `2.0`;
- full current-table key/activity validation, active membership/counts matching
  the success, and valid account references; retained inactive rows keep their
  previous observation IDs;
- same-run history count equals `positions_count`, with unique canonical keys,
  one date, and matching `portfolio_daily.run_id`;
- a valid zero-position result has explicit collection-completeness evidence,
  zero active positions and zero history members for this run, not dummy rows;
- unknown optional fields remain blank, incomplete liabilities do not establish
  zero debt or net worth, and liability details are independently validated;
- all manual tabs are unchanged, and the consumer identifies the accepted
  source and date without mixing runs.

Run a second full execution on the same Europe/Paris day. It must receive a
different run ID while deterministic current/history keys remain unique and the
daily table retains one row for that date. Recheck membership against this
second success; same-day history keys are updated, not appended as duplicates.

Only after acceptance, publish **one** daily workflow and confirm its 07:30
`Europe/Paris` schedule and error-workflow binding. Verify the first scheduled
run as well. A state older than 48 hours is stale even if its terminal status
was successful.

### What this upgrade cannot repair retroactively

Legacy history with blank `run_id` remains retained but does not prove a complete
historical membership. Fresh synchronization can refresh matching same-day keys;
it must not backfill all prior dates or fabricate missing evidence. Explicit
nullable-cell clearing repairs only rows actually rewritten by new runs. Old
dates, untouched inactive rows, and liability details preserved during
incomplete coverage may still contain old values. Never relabel old telemetry
or treat a green new run as a complete repair of historical data.

## 9. If acceptance fails

Keep daily sync unpublished, drain its executions and handlers, and inspect
sanitized diagnostics. Correct credentials, headers, environment, or the
underlying failure, then start a **full new execution**. Do not resume old saved
payloads or manually forge successful terminal records. Prefer forward repair.

Switching code back to `v1.0.0` alone is not a rollback: workflows live in the n8n
database, workbook schema has changed, and old session writers do not participate
in the new coordination protocol. If a coordinated restore is necessary:

1. Stop and drain all writers again. Preserve the post-upgrade workbook and n8n
   state as a separate protected checkpoint before any replacement; restoring
   the earlier checkpoint can discard later data and requires an explicit
   operator decision.
2. Rehearse recovery in an isolated unpublished environment with the matching
   repository revision, image identities, n8n database/encryption key, and
   workbook checkpoint. Do not simply delete column R on a populated workbook.
3. Never restore a Finary session backup. Stop incompatible writers and perform
   fresh human authentication for the selected recovery version.
4. Apply the [backup/restore protocol](operations.md#backup-and-restore) when
   recovering onto 1.1.0, with new full execution identities. Do not replay
   saved old executions into a retained workbook.
5. If returning to 1.0.0, treat its known data-integrity/authentication defects as
   unresolved. Keep automation paused until a safe recovery plan is validated;
   restoring bytes does not make those old behaviors safe.

Record the failure category and recovery checkpoint privately. Do not publish
secrets, raw API responses, or real portfolio data while requesting help.
