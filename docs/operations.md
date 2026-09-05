# Operations

## Operating model

One Docker Compose project owns the local runtime:

- `finary-bridge` on `127.0.0.1:8000`;
- `n8n` on `127.0.0.1:5678`;
- `schema-server` on the private `finary-stack` network.

The repository workflow exports are inactive for safe import. In normal running
state, the deployed **Finary - Daily Sync** workflow is published and active at
07:30 `Europe/Paris`; a new installation publishes it only after a successful
manual run. **Finary - Error Handler** is published so n8n can select it, but it
has no schedule or public trigger.

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
state and the protected Finary session volume.

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
`finary_session_data` volume and leaving `n8n_data` separate. A plain
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
   and restart policy. Write a synthetic sentinel to its dedicated session
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
| Finary email/password | bridge | local `.env` / Compose environment |
| Finary restart session | bridge | `finary_session_data` volume |
| optional bridge API key | bridge and n8n | local `.env` / environment |
| Google OAuth credential | n8n | encrypted `n8n_data` only |
| n8n encryption key | operator | local `.env` plus separate secure backup |
| Google spreadsheet ID | n8n | local `.env` |

Never copy Finary authentication material into n8n or Google Sheets. Never put
Google OAuth material or n8n credential IDs in workflow exports.

## Finary session bootstrap

The bridge API is intentionally non-interactive. Bootstrap or replace its Clerk
session from a terminal using a dedicated adapter. Use `bootstrap_session()` to
force a fresh password/MFA sign-in even when an existing session is still valid:

```bash
docker compose exec -e FINARY_MFA_CODE= finary-bridge python -c '
import getpass
from app.finary_client import FinaryApiClient

client = FinaryApiClient.from_environment(
    second_factor_code_provider=lambda strategy: getpass.getpass(
        f"Enter the one-time Finary {strategy} code: "
    )
)
client.bootstrap_session()
print("Verified session replacement published")
'
```

The command verifies the candidate with an accounts GET before publishing it.
An MFA, upstream, or verification failure leaves existing persisted state intact.
Do not clear state before bootstrapping: a failed candidate must not destroy a
usable session. A storage failure reports failure and may have changed the
revision; if it occurs after atomic file replacement, the new state may already
be present. Check the running bridge before deciding to repeat bootstrap.
Never resume synchronization solely because the command exited successfully.

This writes only the verified session identifier and `__client` cookie to the
bridge-only volume. Bearer JWTs remain memory-only. The session file must remain
mode `0600`. Its mode `0600` sibling `session.json.lock` holds only a non-secret
revision and a cross-process advisory lock. Keep both in the same private mode
`0700` directory on a local filesystem supporting POSIX `flock` and atomic
rename. The configured `FINARY_SESSION_PATH` must resolve to the same shared
volume path for every participating process.

### Replacement protocol and rollout

Hot replacement is supported **only when every writer uses this version of the
adapter/store**. Before the first rollout, unpublish daily sync, stop the old
bridge, and finish or terminate all older bootstrap/helper processes. Rebuild
and recreate the bridge with this version before using the replacement command.
No old writer may remain attached to the volume. Do not remove the volume.
Existing version `1` session JSON is loaded unchanged; the store creates the
revision sidecar on first access. No bearer token or additional authentication
material is added to either file.

Bootstrap signs in and verifies accounts without holding the storage lock,
including while waiting for interactive MFA. Publishing takes a short exclusive
lock and creates a new revision. Every successful renewal and rejection cleanup
compares its observed revision and full state under that same lock before
writing or deleting. Deliberate `clear()` and explicit `save()` also advance the
revision, even for an absent file or identical session/cookie. A competing
bootstrap is an explicit replacement: the last successful publication wins.

Replacement becomes effective for **persisted state at publication**. It does
not cancel an upstream request, revoke an already-issued bearer token, or make
a whole snapshot transactional. The running adapter may continue using its
cached token until its next renewal boundary (normally a 45-second token age,
or an entity 401). If that renewal belongs to an older revision, it cannot
change the replacement file: its access state is invalidated and the current
snapshot can fail with the existing generic authentication error. The next
snapshot's `authenticate()` loads and renews the replacement without another
manual bootstrap. There is no unbounded retry or password/MFA replay in entity
recovery. For immediate adoption, an operator may restart the bridge after
publication; no test-only singleton reset is a runtime recovery mechanism.

The lock order is the adapter's process-local authentication lock, then the
storage lock. Storage methods never acquire the adapter lock or recursively
acquire the storage lock. Network calls and MFA hold no storage lock. Storage
lock acquisition waits at most two seconds by default and reports a sanitized
authentication failure if busy. `/health` and API-key rejection do not use it.

Never edit, copy over, unlink, or restore either session file or lock sidecar
while writers are active. In particular, never delete the lock file: replacing
its inode breaks coordination. Use only the commands here, and exclude the
entire session volume from backups. Network filesystems and older/uncoordinated
writers are unsupported. For damaged permissions or revision metadata, stop
all bridge and helper processes before repairing the private directory; do not
use a raw file deletion as an online recovery shortcut.

Verify the running bridge with a snapshot without printing its portfolio body:

```bash
curl --silent --output /dev/null --write-out '%{http_code}\n' \
  http://127.0.0.1:8000/v2/snapshot
```

Add `-H "X-API-Key: $FINARY_BRIDGE_API_KEY"` when the API key is enabled. A
successful HTTP 200 can legitimately report incomplete liability coverage.
A first authentication failure may be the old adapter abandoning its superseded
revision: retry this check once. For guaranteed verification with B immediately,
restart the bridge before this check; otherwise a still-fresh cached token can
pass it with A. If verification still fails, keep the daily workflow unpublished,
inspect sanitized logs, and resolve the reported category before retrying.
Run one manual sync and inspect `sync_runs` before republishing the schedule.

Repeat bootstrap when authentication returns `FINARY_AUTH_FAILED`, after
password/MFA changes, after explicit session revocation, or after loss of the
session volume. Do not automate TOTP generation or persist TOTP secrets or
backup codes.

To clear rejected state deliberately:

```bash
docker compose exec finary-bridge python -c '
import os
from app.finary_session_store import FileFinarySessionStore
FileFinarySessionStore(os.environ["FINARY_SESSION_PATH"]).clear()
print("Finary session cleared")
'
```

This supersedes pending renewals and sign-ins; it does not immediately revoke
cached bearer tokens or cancel in-flight requests. Stop the bridge as well if
activity must cease immediately. Use deliberate clearing only when discarding
the current session is intended, then bootstrap again. Ordinary recovery uses
the verified replacement command directly, preserving old state on candidate
failure. Malformed/unsupported state is rejected without automatic deletion
because the adapter cannot establish ownership; inspect the storage failure
before using deliberate clearing or offline repair.

## Workbook schema 2.1 migration

Schema `2.1` adds the nullable `run_id` column at the end of
`positions_history`. Existing rows must not be assigned invented membership.
Migrate an existing schema `2.0` workbook offline as follows:

1. unpublish the daily workflow and take an access-controlled workbook backup;
2. append the `run_id` header after `cost_basis_eur` in `positions_history`;
3. leave every existing value in that new column blank;
4. update the `history_rule` and `last_success_rule` rows in the workbook
   `README` tab from `docs/google-sheets-schema.json`;
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
`n8n-execution:{execution_id}` form.

## Consumer-validation adoption

This correction keeps schema `2.1`, headers, deterministic keys and workflow
exports unchanged. The workbook `README` is initialized from the schema and is
not automatically rewritten by portfolio synchronization. Updating repository
files alone does not update an existing workbook or ChatGPT Project.

Operators must:

1. Copy the current `value` and `description` from `readme_entries` in
   `docs/google-sheets-schema.json` for these existing workbook README keys:
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

1. Confirm the bridge health endpoint still returns 200.
2. Inspect sanitized bridge logs for an authentication category, not secrets.
3. Unpublish the daily workflow if failures will repeat.
4. Perform the verified interactive replacement above without pre-clearing state.
   If bootstrap fails, keep synchronization unpublished and fix that failure.
5. restart the bridge for immediate adoption, then call `/v2/snapshot` without
   printing its body; require success before continuing;
6. run one manual synchronization and inspect `sync_runs`;
7. republish only after success.

An authentication failure occurs before portfolio writes and must not alter
current or history sheets.

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
`docs/google-sheets-schema.json`, repair headers exactly, and rerun manually.
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
`n8n-execution:{execution_id}` identity and are idempotent. The n8n action that
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

The daily workflow uses `n8n-execution:{execution_id}` from its own execution.
The error workflow uses only `execution.id` from the originating Error Trigger
payload, never its own execution ID, `execution.retryOf`, or custom run context.
Partial writes and failure telemetry therefore share the same run ID for that
execution. A full new execution gets a new ID; saved-output retries must follow
the recovery procedure above and do not relabel older partial writes.

Before selecting a failure write, the error workflow reads `sync_runs`. An
existing `SUCCESS`, `SUCCESS_WITH_WARNINGS`, or `FAILED` for that exact ID
suppresses the write. This also preserves a success that reached Sheets before
its response was lost. Another run's terminal row does not suppress this failure.
The write matches on `run_id` and touches only sanitized `sync_runs` telemetry;
failure financial totals remain null and are mapped to blank cells with the
exported Sheets configuration.

This read-before-write check protects sequential error replays. It is not a
transaction or a lock: simultaneous handlers or a concurrent terminal writer
can race between the read and write. Concurrent-writer safety has not been
established; avoid overlapping executions during recovery.

The [n8n Error Trigger contract](https://docs.n8n.io/flow-logic/error-handling/)
shows a string source execution ID, which may be absent when the execution was
not saved or the trigger itself failed. If it is missing, empty, or not a string,
`Prepare Sanitized Failure` stops with `SOURCE_EXECUTION_ID_UNAVAILABLE` and
emits no terminal row. Inspect the failed error-handler execution in n8n for
this generic diagnostic. Such failures are invisible to workbook-only consumers;
absence of a `FAILED` row is not evidence that synchronization succeeded.
No ID is fabricated from timestamps, retry ancestry, or the handler execution.

## Backup and restore

Back up:

- the `n8n_data` volume;
- the exact `N8N_ENCRYPTION_KEY`, stored separately from the volume backup;
- the private Google workbook through an access-controlled Google export or
  copy appropriate to your recovery policy.

Do **not** back up `finary_session_data`. A restored environment must use a
fresh interactive Finary bootstrap.

Before backing up, unpublish the schedule and stop the Compose project cleanly.
Use Docker's documented volume-backup method for your platform; do not copy a
live SQLite database opportunistically. Record image digests and repository
revision alongside the backup.

Restore into an isolated, unpublished stack first:

1. restore `n8n_data` and the matching encryption key;
2. start Compose and verify health endpoints;
3. verify n8n can decrypt the Google credential;
4. perform a fresh Finary bootstrap;
5. confirm `/v2/snapshot` structurally succeeds;
6. run one manual sync and verify idempotency and last-valid-state semantics;
7. publish the schedule only after those checks.

## Credential rotation

- **Finary password or MFA:** unpublish daily sync, update `.env`, recreate the
  bridge with the updated environment, run the verified replacement without
  pre-clearing, restart for immediate adoption, test a snapshot and manual sync,
  then republish. Leave sync unpublished if any step fails.
- **Bridge API key:** update bridge and n8n environment together, recreate both
  containers, then verify a manual run.
- **Google OAuth:** reconnect in n8n and reassign every Sheets node before a
  manual run.
- **n8n encryption key:** follow n8n's supported key-rotation procedure. Do not
  simply replace the environment value; existing credentials would become
  unreadable.

After any rotation, inspect logs and `sync_runs` for sanitized output and ensure
no secret was copied into execution data or the workbook.
