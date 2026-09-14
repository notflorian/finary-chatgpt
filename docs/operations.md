# Operations

Application 2.0.0 supports only official MCP; use the [operator runbook](mcp-operations.md)
for independent OAuth and MCP synchronization. Workbook 2.1 adoption/recovery
sections below are frozen references pending removal, not setup instructions for
this bridge. Its legacy workflow exports cannot call the removed V1/V2 routes.

## Operating model

One Docker Compose project owns the local runtime:

- `finary-bridge` on `127.0.0.1:8000`;
- `n8n` on `127.0.0.1:5678`;
- `schema-server` on the private `finary-stack` network.

The repository workflow exports are inactive for safe import. The supported
**Finary MCP Portfolio Sync** runs at 07:30 `Europe/Paris` when published, with
sanitized failure handling inside its own graph. Publish only after operator
acceptance and a successful manual run. Do not activate the frozen legacy daily
workflow or its separate error handler against this bridge.

## Start, verify, and stop

Start or refresh the stack:

```bash
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:5678/healthz
```

Inspect logs without dumping environment variables:

```bash
docker compose logs --tail=100 finary-bridge
docker compose logs --tail=100 n8n
```

Stop containers while preserving state:

```bash
docker compose down
```

Do not use `docker compose down -v` during routine operation. It deletes n8n
state and protected MCP OAuth state.

### Automatic restart and its limits

All three services use `restart: unless-stopped`. Docker restarts containers
after an unexpected process exit and resumes running containers when the daemon
returns. An intentional `docker compose stop finary-bridge` remains respected,
including across daemon restarts; use `docker compose start finary-bridge` to
resume it. `docker compose down` removes containers but preserves named volumes
unless `-v` is supplied. See the official
[Docker restart policy documentation](https://docs.docker.com/engine/containers/start-containers-automatically/),
including the successful-start condition of at least 10 seconds of uptime.

An `unhealthy` health check alone does not trigger this restart policy. Restarting
does not repair revoked Finary credentials or guarantee a successful upstream
synchronization. Compose's `service_healthy` dependencies gate Compose startup;
they do not continuously enforce readiness or order daemon-driven recovery.
Verify `/health`, the schema endpoint, and n8n's `/healthz` after recovery.

To deploy only this policy change, an operator can run
`docker compose up -d --no-deps finary-bridge` from the existing project. This
may recreate the bridge and briefly interrupt requests, while reusing its
`finary_mcp_data` volume and leaving `n8n_data` separate. A plain
`docker compose restart` does not apply a changed Compose configuration.

### Isolated recovery verification

Never run failure injection against production. Use a unique Compose project
name, a temporary configuration resolved with `--env-file /dev/null` and an
explicit synthetic environment, fresh project-scoped volumes, and dynamically
assigned localhost ports where supported (otherwise probe `/health` inside the
container). Disable external network access for test containers; keep workflows
inactive and use only local health endpoints. Do not mount any existing session
or n8n volume or store sentinel data as a session file.

1. Start the disposable bridge with the canonical image/build, health check,
   and restart policy. Write a synthetic sentinel to its dedicated synthetic state
   volume and another to the separate test n8n volume using a network-disabled
   helper. Record the container ID and `RestartCount` with `docker inspect`.
2. Wait for `/health` and at least 10 seconds of continuous container uptime.
   Through `docker compose --env-file /dev/null -p "$test_project"
   -f "$test_config" exec -T finary-bridge`, execute
   `python -c 'import os, signal; os.kill(1, signal.SIGTERM)'` to terminate PID 1
   from inside the container. Uvicorn handles `SIGTERM` and exits without
   Docker marking it as an operator stop. Do not use `compose restart` or an
   operator stop as a process-exit simulation.
3. Within 60 seconds, require the same container ID, an increased restart count,
   and a successful `/health` response. Read and compare both sentinels.
4. Run `docker compose --env-file /dev/null -p "$test_project"
   -f "$test_config" stop finary-bridge`.
   Observe for 15 seconds and require that the container stays stopped with no
   restart-count increase. Read both sentinels using network-disabled helpers
   attached only to their respective disposable volumes.
5. Test daemon/host recovery only on a dedicated disposable daemon or VM. Start
   the test services, wait for health and 10 seconds of uptime, then restart
   that daemon/VM. Check local service availability and both sentinels. Repeat
   with the bridge intentionally stopped and require it to stay stopped. A
   unique project does not authorize restarting a shared daemon or host.
6. Clean up only the disposable project's containers, network, volumes, helper
   containers, and temporary files. Scope every command to the recorded test
   project/resources; never prune or remove production volumes.

Configuration checks, process-exit recovery, and daemon/host recovery are
separate evidence. Health and sentinel checks do not prove synchronization;
any additional snapshot/workflow test must use fake upstreams and a Sheets stub.

## Required runtime configuration

Keep `.env` mode-restricted and outside version control. The important
separation is:

| Secret or identifier | Owner | Storage |
| --- | --- | --- |
| Independent MCP renewable OAuth state | bridge | `finary_mcp_data` volume |
| optional bridge API key | bridge and n8n | local `.env` / environment |
| Google OAuth credential | n8n | encrypted `n8n_data` only |
| n8n encryption key | operator | local `.env` plus separate secure backup |
| Google spreadsheet ID | n8n | local `.env` |

Never copy Finary authentication material into n8n or Google Sheets. Never put
Google OAuth material or n8n credential IDs in workflow exports.

## Independent MCP OAuth bootstrap

Use the [official OAuth procedure](mcp-operations.md#backups-and-independent-oauth).
The verified issuer and required endpoints on `https://clerk.finary.com` remain
allowlisted. They are official OAuth, distinct from the removed private Clerk
password/cookie/MFA implementation. No private credential variables, private
bootstrap/replacement commands or session-clearing CLI remain supported.
Routes never prompt, register a client or request consent. Protect the renewable
state and preserve its CAS/lease controls; access tokens remain memory-only.
Old private session volumes are operator data: do not read, convert or delete them.

## Workbook schema 2.1 migration

For a complete application upgrade from `v1.0.0`, follow the
[1.0.0 to 1.1.0 migration guide](migration-1.0-to-1.1.md). The schema-only
steps below do not cover all required workflow, session, and consumer changes.

Schema `2.1` adds the nullable `run_id` column at the end of
`positions_history`. Existing rows must not be assigned invented membership.
Migrate an existing schema `2.0` workbook offline as follows:

1. unpublish the daily workflow and take an access-controlled workbook backup;
2. append the `run_id` header after `cost_basis_eur` in `positions_history`;
3. leave every existing value in that new column blank;
4. update the `history_rule` and `last_success_rule` rows in the workbook
   `README` tab from `docs/google-sheets-schema-v2.json`;
5. import the schema `2.1` workflow exports and restore their Google credential
   bindings;
6. run one manual synchronization and verify that its history row count equals
   `sync_runs.positions_count` and that history and `portfolio_daily` carry the
   successful `run_id`;
7. publish the schedule only after that verification succeeds.

Legacy history remains physically intact. Blank legacy `run_id` values cannot
be mapped reliably to old runs, so those rows are valuations rather than proven
complete memberships. The first successful schema `2.1` run establishes a
selectable complete state for its Europe/Paris date.

Workbooks already on schema `2.1` need no column change for opaque execution
identities. Import the corrected inactive workflow exports and keep existing
timestamp-shaped `run_id` values unchanged; equality-based history selection
continues to interpret them. New executions use the
`n8n-run:{execution_id}:{uuid_v4}` form described below; old
`n8n-execution:{execution_id}` IDs also remain valid opaque read keys.

## Consumer-validation adoption

This correction keeps schema `2.1`, headers, deterministic keys and workflow
exports unchanged. The workbook `README` is initialized from the schema and is
not automatically rewritten by portfolio synchronization. Updating repository
files alone does not update an existing workbook or ChatGPT Project.

Operators must:

1. Copy the current `value` and `description` from `readme_entries` in
   `docs/google-sheets-schema-v2.json` for these existing workbook README keys:
   `current_state_rule`, `history_rule`, `gross_assets_rule`,
   `failed_snapshot_rule`, `liability_rule`, `last_known_liability_rule`, and
   `last_success_rule`. Preserve other entries and all portfolio/manual rows.
2. Replace the uploaded `finary-portfolio-data-knowledge.md` source in each
   consuming ChatGPT Project with this revision. Remove obsolete duplicate
   references and update any Project reading instructions that only filter
   `is_active = TRUE`, following [chatgpt.md](chatgpt.md#how-chatgpt-should-read-the-workbook).
3. Verify the consumer reports accepted/rejected data sources, full-table
   membership and counts, explicit dated historical fallback, and independent
   last-known complete liability provenance. Test the interruption scenarios
   using synthetic data, not partial writes to a production workbook.

No workbook or Project update is performed by the repository tests. The
executable consumer specification is test-only, not a deployed enforcement
layer. No workflow import, publication or service restart is required solely for
this correction. The existing completion-timestamp behavior is unchanged.

## Net-worth baseline correction adoption

The comparison fix preserves workbook schema `2.1`, headers, keys, and existing
rows. No workbook README update or data repair is required. The daily workflow
now reads all `sync_runs` statuses before row preparation, including failures
and physical duplicates. The new **Read Sync Runs** node must receive the same
Google Sheets credential as the other reads. It uses **Execute Once**, successful
empty-read continuation, three bounded attempts, and the existing workflow
timeout. Read errors stop before portfolio writes and use the sanitized error
handler; they must never be replaced with empty evidence.

The baseline is the newest unambiguous, independently validated retained
`COMPLETE` daily aggregate by parsed successful terminal completion time,
excluding the current execution. It can be older than the latest successful
execution when that execution's daily evidence was overwritten. Telemetry alone
cannot reconstruct the missing aggregate. Missing, conflicting, duplicate, or
invalid evidence makes that candidate unusable; tied newest eligible completion
instants leave the comparison blank. Zero remains a valid previous amount, but
its relative change is blank. See the
[eligibility and valuation-change rules](finary-portfolio-data-knowledge.md#workflow-net-worth-comparison-baseline).

For deployment, an operator must unpublish the daily schedule, let running
executions settle, import both corrected inactive workflow exports, restore all
Google credential bindings and the Error Workflow link, and verify a manual run
before publishing again. Replace the ChatGPT Project knowledge reference if it
should describe this comparison behavior. Repository tests perform none of these
operator actions and never rewrite prior telemetry. No service restart or schema
migration is required for this correction.

Sequential Sheets reads are not a transaction. Neither matching run IDs nor
identical repeated reads makes overlapping executions atomic. Avoid overlapping
executions during adoption and recovery; terminal payload timing and final-write
retry semantics remain as described under [Partial write](#partial-write).

## Zero-position synchronization adoption

This correction adds `coverage.position_collections` to API schema `2.0` and
keeps workbook schema `2.1`, headers, keys and README entries unchanged. It needs
both the updated bridge and daily workflow. Older nonempty payloads remain
accepted; an older bridge cannot authorize zero-position writes. Older workflows
still reject zero positions even with the new bridge. Update any strict API
client response allowlist for the additive field.

During an operator-controlled maintenance window, unpublish the daily schedule
and let existing executions settle. Rebuild/recreate the bridge with this
revision, preserving its session volume, and reimport the corrected inactive
daily export. Restore all Sheets credentials and the error-workflow link using
the installation checklist below. Keep **Execute Once** on reads/preflights and
all-row processing on writes. The error-handler export is unchanged. Replace the
uploaded knowledge reference and update Project instructions for the
[zero-position rules](finary-portfolio-data-knowledge.md#zero-positions-with-successful-evidence).
No workbook column migration, history cleanup or manual-sheet edit is needed.

Verify the new branches with the isolated synthetic runtime regression described
in [development.md](development.md#required-local-checks), never by deleting real
holdings or forcing an upstream failure. Before the operator republishes, check
a manual run's required writes and unique terminal success. For a legitimately
empty position snapshot, expect zero active positions, preserved observation
IDs/timestamps on inactive rows, unchanged retained history, updated accounts and
daily totals, and `positions_count = 0`. A count-change or incomplete-liability
warning correctly gives `SUCCESS_WITH_WARNINGS`; otherwise expect `SUCCESS`.
Repeated runs must preserve unique keys and one terminal record per execution.
No deployment, live workbook write or workflow activation is performed by tests.

## Prewrite contract validation adoption

The daily workflow validates snapshot inputs and all prepared write batches.
API schema `2.0`, workbook schema `2.1`, headers, manual sheets and the bridge
remain unchanged. The canonical FastAPI response model normally rejects the
malformed inputs this defense-in-depth gate now catches independently.

During an operator-controlled maintenance window, unpublish the schedule and
let executions settle, then reimport the corrected **inactive daily workflow**.
Restore its Google credential bindings and Error Workflow link using the
installation checklist below. The error-handler export is unchanged. No bridge
restart, session-file change, workbook migration or history cleanup is needed.
Check the isolated synthetic regressions in
[development.md](development.md#required-local-checks) before an operator verifies
a normal manual run and republishes. Repository checks do not perform these
operator actions.

A contract failure identifies only a trusted sheet/field path or a fixed error
code. Input failures may record sanitized `FAILED` telemetry; row-preparation
failures stop before portfolio writes and use the existing error workflow.
Missing or corrupt required values on a retained row that must be inactivated
now stop preparation. Investigate the named field through the normal operator
process; the workflow must not guess a name, classification, observation time or
run ID to continue. Optional Sheets blanks and supported numeric/boolean read
encodings remain valid. Under `PARTIAL` or `UNAVAILABLE` coverage, liability
rows remain untouched even if their old cells are corrupt. Unrelated retained
history is neither rewritten nor automatically repaired.

Saved-data retries with a stale execution identity now also fail at preparation;
the existing terminal identity check remains. Recover by starting a full new
execution, with the existing exception for retrying only the already-finalized
terminal Sheets write after all required writes succeeded. Sheets writes remain
nontransactional: prewrite validation cannot prevent later service failures or
concurrent edits, so consumer membership checks and recovery rules still apply.

## Nullable-cell clearing adoption

The corrected exports explicitly clear intentional nullable cells during all
eight Sheets write paths: current accounts, positions, authorized COMPLETE
liabilities, position history, daily aggregates, successful telemetry, structured
failed telemetry, and operational failure telemetry. Validation and calculations
keep null values; only the final Sheets payload encodes them as empty strings.
The pinned n8n auto-mapping path skips null updates even with
`allowEmptyValues=true`, so earlier executions could update a run ID while
retaining an old amount or optional string in the same row.

During an operator-controlled maintenance window:

1. Unpublish the daily schedule, stop new manual executions, and let daily and
   error executions settle. Preserve an access-controlled workbook backup. Do
   not resume old saved/pinned node data after adopting the corrected exports.
2. Import **both inactive exports**, restore every Google credential binding,
   the local n8n API credential on **Fetch Source Execution**, and the daily
   Error Workflow link. Follow the installation checklist below; retain RAW
   formatting, all-row writes, and Execute Once on reads/preflights.
3. Start a **complete new manual synchronization**. Verify terminal success,
   current membership/counts, same-day history membership, and actual blank
   cells where the new snapshot has unknown values. Matching run IDs alone
   cannot prove that cells written by the older exports were accurate.
4. Republish the schedule only after the new successful state passes the
   [first-run checks](#first-run-verification).

API schema `2.0` and workbook schema `2.1` stay unchanged; no column migration,
bridge restart, manual-sheet modification or history deletion is needed. A new
successful run refreshes observed current data and its same-day history keys.
Liability details refresh only with COMPLETE coverage. Inactive retained rows
keep their last observation; absent same-day history keys remain retained.
This does **not** reconstruct historical values from earlier dates or repair
unobserved retained data. Do not relabel old observations or infer their missing
values. Any historical investigation requires separate evidence and operator
action. Repository validation performs no production repair or publication.

## n8n installation checklist

After importing both JSON exports:

1. assign the same Google Sheets OAuth2 credential to every Google Sheets node
   in both workflows;
2. confirm `FINARY_GOOGLE_SHEET_ID`, `FINARY_BRIDGE_URL`, and
   `FINARY_SCHEMA_URL` are available to n8n;
3. publish the error handler;
4. select it in the daily workflow's **Error Workflow** setting;
5. keep each Sheets read/preflight node on **Execute Once**;
6. keep row-write nodes processing every incoming row;
7. run the daily workflow manually;
8. publish the daily workflow only after workbook and telemetry verification.

The Google OAuth assignment is per node. A missed failure-branch credential can
remain hidden until that branch executes.

## First-run verification

After a manual execution, inspect the terminal `sync_runs` row and workbook:

- status is `SUCCESS` or `SUCCESS_WITH_WARNINGS`;
- the recorded snapshot API `schema_version` is `2.0`;
- full current tables have non-empty unique canonical keys and valid activity
  flags; do not prefilter or deduplicate;
- active account and position `last_seen_run_id` values match the selected
  successful run, and active counts equal valid finite non-negative integer
  `accounts_count` and `positions_count` (missing is not zero);
- active positions reference validated active accounts, and their keys match
  independently validated same-run history;
- retained inactive rows are excluded from counts; their older observation IDs
  are allowed even after a later execution wrote the inactivation;
- liability details independently pass membership and `liabilities_count`
  checks against the latest successful `COMPLETE` run;
- history rows for the successful `run_id` equal `positions_count`, have unique
  position keys, share one date, and match `portfolio_daily.run_id`;
- blank numeric fields remain blank;
- `liability_coverage` agrees with nullability of liability and net-worth
  totals;
- no manual sheet changed.

Run the same workflow once more on the same day. Counts should remain stable,
current keys should not duplicate, `positions_history` should upsert the same
daily keys, and `portfolio_daily` should still have one row for the date.

## Monitoring

Select the latest successful execution using parsed timezone-aware
`completed_at` and `SUCCESS` / `SUCCESS_WITH_WARNINGS`. Require exactly one
terminal record per candidate across all statuses; conflicting duplicates,
missing evidence and tied newest instants cannot establish a unique latest
success. IDs are opaque equality keys. A later `FAILED` record does not advance
freshness, and absence of failure telemetry does not prove success.

Then apply the [consumer validation procedure](finary-portfolio-data-knowledge.md#current-asset-membership-and-completeness).
Physical current tables may have been overwritten since that success; validate
full-table keys, flags, active membership/counts and account references before
using them. Do not silently discard foreign rows or accept an incomplete subset.
Check liabilities independently against the latest successful COMPLETE run,
even when newer incomplete assets replaced the same-day daily row.

For a date, validate its unique daily row and successful terminal evidence,
coverage and shared totals. Independently require canonical unique history keys,
matching date/run/generated timestamp and exactly valid `positions_count`
members. A terminal success alone cannot recover overwritten same-day history.
If current rows fail but history passes, retain that history. If history fails,
use an explicitly older valid date or report details unavailable; do not mix
runs. Validated daily aggregates can remain usable with their own provenance.
A selected state's completion time older than 48 hours is stale: disclose it
and investigate, even if a more recent successful execution exists.

Sequential reads do not provide transactional consistency. Reject observed
changes and inconsistencies; repeat full reads after writes settle. Identical
repeat reads still cannot rule out an unobserved concurrent write. A consumer
must not claim the checks create an atomic portfolio snapshot.

Common warnings:

- `LIABILITY_COVERAGE_UNAVAILABLE`: liabilities and net worth are unknown, not
  zero;
- `PARTIAL_POSITION_EUR_COVERAGE`: position allocation covers only active
  positions with verified EUR values;
- a net-worth move above the configured threshold is a warning only when both
  compared totals are known.

The error handler writes a sanitized `sync_runs` record for uncaught workflow,
Code-node, or Google Sheets failures when telemetry remains writable. It does
not duplicate an existing terminal record for the same run.

## Kill switch

Unpublish **Finary - Daily Sync** in the n8n UI. If the UI is unavailable, list
workflow IDs and unpublish the daily workflow from the container:

```bash
docker compose exec -T n8n n8n list:workflow
docker compose exec -T n8n n8n unpublish:workflow --id=<daily-workflow-id>
```

Unpublishing must not delete the workflow, workbook, execution history, or
Docker volumes. Confirm the schedule is inactive before any risky repair.

## Failure recovery

### Finary authentication failure

Verify local `/health`, pause MCP synchronization, and inspect only sanitized
`MCP_AUTH_UNAVAILABLE` diagnostics. Follow the independent OAuth runbook for an
explicitly authorized connection replacement. Verify `/v3/snapshot` and a full
manual MCP sync before resuming the schedule. Never fall back to private auth.

### Google credential failure

`GOOGLE_AUTH_FAILED` usually means a missing, revoked, or misassigned n8n
credential. Reconnect the OAuth credential, reassign it to every Sheets node on
both success and failure branches, then retry manually. Do not store exported
OAuth tokens in the repository.

### Google quota or temporary failure

Sheets nodes make at most three attempts with a fixed five-second delay. The
installed n8n runtime does not provide native exponential backoff for these
nodes. On `GOOGLE_RATE_LIMITED` or `GOOGLE_TEMPORARY_FAILURE`:

1. stop manual retries and let the per-minute window reset;
2. verify all read and preflight nodes use **Execute Once**;
3. inspect whether a preceding high-row-count read is multiplying requests;
4. rerun once after the window resets;
5. request a Google quota increase only after eliminating amplification.

The daily and error workflows have finite execution timeouts of 300 and 120
seconds respectively. A stale running execution may be stopped in n8n before a
manual retry.

### Header or schema mismatch

The workflow fails before portfolio writes when a tab name, header, order, or
schema version drifts. Compare the workbook against
`docs/google-sheets-schema-v2.json`, repair headers exactly, and rerun manually.
Never rename a key or replace blank numeric cells with text to bypass the gate.

### Partial write

Google Sheets does not provide one transaction across all tabs. If a failure
occurs after some upserts:

1. unpublish the schedule;
2. identify the last completed write node and the affected `run_id`;
3. verify manual sheets were not altered and validate liability details against
   their last successful COMPLETE run; a failed COMPLETE write may invalidate
   them even when an earlier daily aggregate survives;
4. fix the underlying credential, quota, or header problem;
5. start a full new workflow execution for the same logical date;
6. verify deterministic keys repaired rows without duplicates; validate full
   current membership/counts and account references, same-run history key sets,
   daily/history membership, and independent COMPLETE liability membership;
7. verify one terminal telemetry row remains for the new run.

While recovery is pending, reject invalid current tables. Use only independently
validated history with its explicit date/run/freshness and retained fields, or
report detail unavailable. Never enrich fallback history from invalid current
rows or invent liability history. Keep independently validated aggregates
separate from unavailable details. Do not delete current or historical rows as
a recovery shortcut.

Sheets node retries configured inside a running execution retain its opaque
`n8n-run:{execution_id}:{uuid_v4}` identity and are idempotent. The n8n action that
retries a saved failed execution creates a new n8n execution but can reuse saved
node output containing the old identity. The workflow blocks terminal success
when it detects that mismatch. Use a full new workflow execution after a
partial-write failure. Retrying only `Record Successful Sync` is safe when the
execution had already completed every required portfolio write and reached that
final node.

For `SUCCESS` and `SUCCESS_WITH_WARNINGS`, `Select Success Run` finalizes
`completed_at` after all required account, position, conditional liability,
position-history, and daily-summary writes have succeeded, immediately before
submitting `Record Successful Sync`. Both timing fields use one captured instant:
`completed_at` is its timezone-aware UTC timestamp, and `duration_ms` is the
elapsed epoch milliseconds since the original execution's `started_epoch_ms`,
clamped to zero if the clock moves backward. Invalid timing input stops success
finalization. The timing origin and prepared row must both match the current
execution identity; a stale identity is never relabeled.

This interval includes initialization, reads, validation, portfolio writes, and
their native retries. It excludes the terminal Sheets request's response time
and subsequent retries of that request. Retrying only `Record Successful Sync`
reuses the finalized payload and its original `run_id` upsert key, including the
two timing fields. No recursive telemetry update measures the terminal write.
Snapshot timestamps, business dates, and schedules still use their existing
`Europe/Paris` rules. These timestamps describe payload finalization, not an
atomic Sheets commit or a globally serialized completion order; overlapping
writes and sequential reads still require the documented consumer validation.
Existing telemetry is not rewritten by adopting this workflow.

### Error correlation and terminal replay

`Initialize Run` generates one cryptographically random UUID using Node's
`crypto.randomUUID()` and combines it with the verified `$execution.id` as
`n8n-run:{execution_id}:{uuid_v4}`. The saved node output owns this identity and
its timing origin. A fresh initialization generates fresh entropy even when an
older database or a fresh installation reuses the same execution number. There
is no operator-managed identity scope, shared default, or scope rotation.
Ordinary restarts do not change saved payloads. Missing crypto support, malformed
execution IDs, and invalid saved run context stop the execution without guessing.

The error workflow reads the **originating** execution through n8n's local
`GET /api/v1/executions/{id}?includeData=true` API. `Fetch Source Execution`
uses a runtime-only **n8n API** credential and a fixed loopback URL, with a
10-second timeout and up to three native transport attempts. `Resolve Source Execution` requires the
same execution ID, workflow ID, mode, and exact persisted n8n context
(`version`, `establishedAt`, `source`) supplied by Error Trigger. It then reads
exactly one saved `Initialize Run` output and checks that output's execution
identity and timing. The context timestamp is an equality check, never an ID
generator or approximate lookup. Retry ancestry, custom trigger fields and the
handler's execution ID are never used to infer the run.

These capabilities are verified in the pinned n8n sources:
[Error Trigger dispatch](https://github.com/n8n-io/n8n/blob/n8n%402.35.5/packages/cli/src/execution-lifecycle/execute-error-workflow.ts),
[persistence before dispatch](https://github.com/n8n-io/n8n/blob/n8n%402.35.5/packages/cli/src/execution-lifecycle/execution-lifecycle-hooks.ts),
and [execution retrieval](https://github.com/n8n-io/n8n/blob/n8n%402.35.5/packages/cli/src/public-api/v1/handlers/executions/executions.handler.ts).
The daily export explicitly retains failed execution data. Do not disable that
setting or prune/redact the source data while its error handling is pending.
The lookup remains inside n8n; retrieved execution data is never written to
Sheets or sent to the bridge.

Before the first portfolio write, `Prepare Validated Rows` rejects **any**
existing row with the new run ID, regardless of terminal status. Success
finalization rereads `sync_runs` and applies the same check. The structured
invalid-snapshot branch also reads `sync_runs` before preparing failed telemetry.
Both failure paths suppress only a single terminal row with the exact run ID
and original `started_at`; another start, an unknown status, or duplicate rows
raises `RUN_IDENTITY_COLLISION`. Existing rows remain intact. Native terminal
write retries reuse their finalized input and original timing; no intervening
Code node regenerates or relabels the payload. A saved-data retry resuming earlier
Code nodes is rejected when its new execution ID does not match the saved run.
Use a full new execution for recovery from partial writes.

Missing/invalid source IDs produce `SOURCE_EXECUTION_ID_UNAVAILABLE`. A failed
API read, unavailable/redacted/pruned source data, missing initialization or
mismatched source context produces `SOURCE_RUN_IDENTITY_UNAVAILABLE`; stale
saved identities produce `STALE_EXECUTION_IDENTITY`. No correlated terminal row
is fabricated. Inspect the failed handler in n8n for the sanitized diagnostic.
Failures before initialization therefore have no workbook telemetry. Absence
of `FAILED` never establishes success. Complete error replays preserve an
existing success even when the original terminal response was lost. Failure
financial totals remain null and map to blank cells.

The checks protect sequential writes and replays. They are **not** a transaction
or a lock: simultaneous handlers, overlapping syncs or arbitrary writers can
race between reads and writes. Keep one writer and let both sync and error
executions settle before recovery; retain the consumer membership/count checks.

### Adopting restore-safe run identities

1. Unpublish the schedule and stop new manual syncs. Finish or cancel and drain
   every running, waiting, queued, or saved execution and its error handler.
   Resolve any retry of an already-finalized terminal write **before** adoption.
   Do not resume old exported code or pinned/saved node data after adoption.
2. Import **both** inactive exports, restore the daily-to-error-workflow binding
   and every Google credential binding, including the two new terminal reads.
3. Create a local n8n API credential with access to the daily execution data
   (use `execution:read` scope where available), base URL
   `http://127.0.0.1:5678/api/v1`, and bind it only to `Fetch Source Execution`.
   Store the API key in n8n's credential store, never `.env`, exports or Sheets.
   Missing, expired, or inaccessible credentials fail closed; there is no fallback
   to a database execution number. Keep `saveDataErrorExecution = all`.
4. Apply the Compose n8n environment setting `NODE_FUNCTION_ALLOW_BUILTIN=crypto`
   during the planned maintenance window. It permits only the built-in used for
   UUID generation. This is an operator action; importing exports alone does not
   change the running container environment.
5. Verify a new manual success and a controlled failure using an isolated test
   workbook before publishing through the normal acceptance procedure. Verify
   the source lookup and identical run IDs in the resulting synthetic telemetry.

No workbook columns, API version or workbook version change. Retain every old
`n8n-execution` or timestamp-shaped run ID as an opaque equality key. No retained
history is rewritten. The reference reader's rules remain unchanged.

## Backup and restore

Back up:

- the `n8n_data` volume;
- the exact `N8N_ENCRYPTION_KEY`, stored separately from the volume backup;
- the private Google workbook through an access-controlled Google export or
  copy appropriate to your recovery policy.

Do **not** back up `finary_mcp_data`. A restored environment must use a
fresh independently authorized MCP OAuth connection.

Before backing up, unpublish the schedule, drain daily and error executions
as described above, and stop the Compose project cleanly.
Use Docker's documented volume-backup method for your platform; do not copy a
live SQLite database opportunistically. Record image digests and repository
revision alongside the backup.

Restore into an isolated, unpublished stack first:

1. stop new work and drain source executions and delayed error handlers before
   replacing the database or reconnecting a fresh installation to the workbook.
   Do not carry queued error deliveries across database replacement: the API
   lookup must refer to the same database as its originating execution. An exact
   context mismatch is rejected, but timestamps are not a global identity proof.
   Cancel saved/waiting executions restored from the backup; start full new runs;
2. restore `n8n_data` and the matching encryption key;
3. adopt both current exports and the crypto setting while unpublished; verify
   the Google bindings and local n8n API credential. A fresh installation needs
   its own API credential; an old key may require replacement after restoration;
4. start Compose, verify health and establish independent MCP OAuth;
5. confirm `/v3/snapshot` structurally succeeds;
6. start one full new manual sync. A reused database execution number now gets a
   fresh UUID, so retained terminals/history remain distinct. Verify current,
   history, daily and independent liability membership and test error correlation;
7. publish the schedule only after those checks. Never replay saved old terminal
   payloads into the retained workbook as part of restoring a backup.

## Credential rotation

- **MCP OAuth:** pause synchronization and follow the independent OAuth runbook;
  replacement and revocation require explicit operator intent. Verify an
  authorized snapshot and manual sync before resuming.
- **Bridge API key:** update bridge and n8n environment together, recreate both
  containers, then verify a manual run.
- **Google OAuth:** reconnect in n8n and reassign every Sheets node before a
  manual run.
- **n8n encryption key:** follow n8n's supported key-rotation procedure. Do not
  simply replace the environment value; existing credentials would become
  unreadable.

After any rotation, inspect logs and `sync_runs` for sanitized output and ensure
no secret was copied into execution data or the workbook.
