# Operations runbook

This runbook covers the local repository Compose stack: `finary-bridge`, n8n, the local
canonical-schema service, Google Sheets, and the two importable workflows. It
does not change the Phase 5 synchronization semantics.

## Safety state

The protected live `Finary - Daily Sync` workflow is published after explicit
Phase 12 approval. It is the only production schedule and runs at 07:30 in
`Europe/Paris`. The repository export remains inactive for safe import. Schema
`2.0` returns truthful asset state with explicit `PARTIAL`/`UNAVAILABLE`
coverage and never fabricates liability-dependent totals. The first natural
scheduled execution passed acceptance; see `production-activation.md`.

The activation path is tracked in GitHub. Liability investigation
[#13](https://github.com/notflorian/finary-chatgpt/issues/13) produced the
[Outcome B evidence and versioned proposal](liability-coverage-investigation.md),
but schema `1.0` completeness remains unavailable. Authentication
[#14](https://github.com/notflorian/finary-chatgpt/issues/14) concluded with
Outcome A: the protected bridge-only Clerk session survives routine restarts
without persisting MFA material or bearer JWTs. Complete liability coverage
Issue [#23](https://github.com/notflorian/finary-chatgpt/issues/23) implements
the canonical schema-2.0 contract and inactive migration artifacts. End-to-end
acceptance [#15](https://github.com/notflorian/finary-chatgpt/issues/15) passed;
sanitized evidence is recorded in `end-to-end-acceptance.md`.
Compose migration [#16](https://github.com/notflorian/finary-chatgpt/issues/16)
is accepted; sanitized evidence is recorded in `compose-migration.md`. CI
[#17](https://github.com/notflorian/finary-chatgpt/issues/17) is implemented;
all four GitHub-hosted checks have been observed green. Production activation
[#18](https://github.com/notflorian/finary-chatgpt/issues/18) passed its live
activation checks and is completed by merging its PR. ChatGPT connection
[#19](https://github.com/notflorian/finary-chatgpt/issues/19) follows that merge.

## Start and verify the local stack

1. Copy `.env.example` to an ignored `.env` and set strong values for
   `N8N_ENCRYPTION_KEY` and, if used, `FINARY_BRIDGE_API_KEY`.
2. Set `FINARY_GOOGLE_SHEET_ID`. Keep Finary credentials only in the local
   environment file.
3. Start the stack with `docker compose up -d --build`.
4. Check `docker compose ps`, `curl -fsS http://127.0.0.1:8000/health`, and
   `curl -fsS http://127.0.0.1:5678/healthz`.
5. From the n8n container, the schema is available at
   `http://schema-server/google-sheets-schema.json`.

Set `FINARY_GOOGLE_SHEET_ID` to the canonical schema-2.0 workbook, import the
two unsuffixed workflow exports, assign credentials to every Sheets node, and
link the error handler. The pre-production v1 workbook and workflows were
removed after live migration acceptance.

The n8n database and encrypted credentials persist in `n8n_data`. Sensitive
Clerk restart state persists separately in `finary_session_data`, mounted only
into the bridge. The Compose ports bind to localhost only. The schema service
has no host port and mounts the canonical JSON read-only.

The canonical workflows resolve their local bridge, schema, workbook, and
optional API-key settings through n8n's `$env` expressions. Compose therefore
sets `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`, matching the accepted legacy runtime.
Do not expose untrusted workflow editing on this local instance; a workflow
editor can read process environment values under this setting.

Both schema-fetch HTTP nodes read the canonical JSON as text and let their Code
node parse it. This is deliberate compatibility with n8n 2.35.5; selecting the
HTTP node's JSON response mode caused a pre-write parse failure in live
migration validation. In that runtime, the Text-mode full response stores the
payload under `data`; the validation nodes deliberately accept `data`, `body`,
or an already-decoded object.

Open n8n at `http://127.0.0.1:5678`. View bounded recent logs with
`docker compose logs --tail=200 finary-bridge n8n schema-server`; review them
before sharing because execution detail can contain private node input. Routine
lifecycle commands are `docker compose build`, `docker compose up -d`, and
`docker compose down` without `-v`.

Phase 10 made this repository Compose project the only live-stack owner. Do not
start legacy helper containers beside it. Before any lifecycle command, run
`docker compose config --quiet`; after startup, require all three services to
be healthy. A bridge restart must not restart or erase n8n, and an n8n restart
must not modify the workbook merely by starting.

## CI and release gate

Phase 11 defines four stable GitHub Actions checks:

- `tests`
- `static-analysis`
- `repository-contracts`
- `n8n-import`

Reproduce them with the exact commands in `ci.md`. The tests gate reports
pytest failures and unexpected skips; static analysis reports Ruff and mypy
separately; repository contracts identify JSON or quiet Compose failures; and
n8n import uses the real Compose-pinned runtime in network-isolated ephemeral
containers. Do not diagnose CI by printing `.env`, expanded Compose
configuration, workflow execution data, or private fixtures.

The workflow uses GitHub-hosted runners, read-only contents permission, full-
SHA action pins, and no production secrets, live-test flags, cache, or artifact
upload. It cannot access Finary, Google Sheets, Clerk state, the live n8n
instance, or the local Docker host. After the workflow is published and passes,
configure the four stable names as required pull-request checks through a
separate authorized repository-settings change; Phase 11 does not mutate
branch protection.

A green Phase 11 run was necessary but not sufficient for scheduling. Issue
#18 received explicit activation approval after its operational preflight.

## Import and configure workflows

Import, in order:

1. `n8n/workflows/finary-error-handler.json`
2. `n8n/workflows/finary-daily-sync.json`

Assign the same Google Sheets OAuth2 credential to every Google Sheets node in
both workflows. Imported workflow and node IDs are remapped by n8n, so open the
error handler, configure its 120-second timeout, and publish it. It has no
schedule or external trigger. Then open the daily workflow's **Settings**,
choose `Finary - Error Handler`, configure its 300-second timeout, and save
without publishing the daily workflow. Do not add credentials to exported JSON.

Run the daily workflow manually first. Confirm a structured bridge failure adds
one sanitized `FAILED` row to `sync_runs` and changes no portfolio sheet. This
handled branch completes normally and does not invoke the error workflow. The
error workflow handles otherwise uncaught node failures.

The workbook must contain all ten sheets with row-1 headers exactly matching
`docs/google-sheets-schema.json`. Synchronization never owns the manual
`allocation_targets`, `asset_overrides`, or `cashflows` sheets.

## Retries, timeouts, and Google quota

Every Google Sheets node uses n8n's native bounded retry: three total attempts
with five seconds between attempts. n8n 2.35.5 supports only a fixed retry
delay, not exponential backoff; no unsupported backoff behavior is claimed.
The daily workflow timeout is 300 seconds and the error workflow timeout is 120
seconds. Compose also caps executions at 300 seconds.

All Google Sheets reads use `Execute Once`. This is essential: without it, an
upstream multi-row result can cause one Sheets request per input item. Do not
enable `Execute Once` on write nodes because they must process every selected
row. Avoid repeated manual executions within the per-user Google Sheets quota
window. Request higher quota only after eliminating request amplification.

## Monitoring and last successful synchronization

`sync_runs` is append-oriented operational telemetry. A successful run has
status `SUCCESS` or `SUCCESS_WITH_WARNINGS`; a failure has `FAILED`. The last
successful synchronization is the successful/warning row with the newest valid
`completed_at`, never merely the last row. New failures do not move that
success marker.

The error workflow records only sanitized fields. When the original Phase 5
run ID is unavailable it uses `n8n-execution:{execution_id}`. It will not
overwrite any existing terminal row for the same ID. Portfolio values remain
blank on operational failures. Inspect the n8n execution UI for private
diagnostic detail; `sync_runs.error_message` never contains raw exception
messages, stacks, payloads, tokens, cookies, or credentials.

Stable operational error codes are:

- `GOOGLE_AUTH_FAILED`, `GOOGLE_RATE_LIMITED`, `GOOGLE_TEMPORARY_FAILURE`,
  `GOOGLE_SCHEMA_MISMATCH`
- `WORKFLOW_TIMEOUT`, `WRITE_FAILED`, `N8N_EXECUTION_FAILED`
- the existing bridge codes recorded by the main workflow, including
  `FINARY_AUTH_FAILED`, `FINARY_TIMEOUT`, `FINARY_MALFORMED_RESPONSE`,
  `FINARY_UPSTREAM_ERROR`, `FINARY_FEATURE_UNAVAILABLE`, and
  `SNAPSHOT_VALIDATION_FAILED`

If the error workflow itself cannot reach Google Sheets or the local schema,
it cannot safely record a row. Use the n8n execution list as the fallback
diagnostic source and repair the dependency before retrying.

In n8n's Executions view, the most recent row is the last execution, not
necessarily the last success. `SUCCESS_WITH_WARNINGS` is a valid completed run;
inspect `warning_count` and the documented partial-EUR/count-change warnings.
For a stale `RUNNING` execution, open it, note the last executed node, use n8n's
Stop control, and follow the timeout or partial-write recovery path. Never start
a second run while the first is still stopping.

## Production schedule operations

The live `Finary - Daily Sync` workflow is the only production-capable daily
workflow. Its schedule is `30 7 * * *` in `Europe/Paris`. The repository export
remains inactive so importing it cannot start a schedule accidentally; live
publication state belongs only to the protected n8n runtime.

### Immediate kill-switch

Disable the schedule first whenever an unattended run is unsafe or the first
scheduled run fails. In the n8n editor, open `Finary - Daily Sync` and use the
supported **Unpublish** action. The equivalent pinned-runtime CLI is:

```bash
docker compose exec -T n8n n8n unpublish:workflow --id=<live-workflow-id>
```

Resolve the live ID with n8n's supported workflow list/export command; never
place an instance-specific ID in repository files. Verify afterwards that the
daily workflow is inactive and that no other active Schedule Trigger calls
`/v2/snapshot`. Unpublishing must not delete the workflow, `n8n_data`, the
workbook, execution history, or `finary_session_data`, and it must not stop the
error handler. Never use `docker compose down -v` as an incident response.

### Initial scheduled-run policy

After activation, review the first natural 07:30 execution without changing the
cron. Accept `SUCCESS` or only understood `SUCCESS_WITH_WARNINGS`. Verify schema
`2.0`, explicit liability coverage, deterministic current/history/daily keys,
one new telemetry row, unchanged manual sheets, and correct last-success
selection. If the first scheduled execution is `FAILED`, unpublish immediately
before recovery. For `PARTIAL` or `UNAVAILABLE`, liability and net-worth totals
must remain blank and `liabilities_current` must remain untouched.

Classify failures before reactivation:

- `FINARY_AUTH_FAILED`: unpublish, perform one transient MFA bootstrap, verify
  `/v2/snapshot`, and require a successful manual run;
- `GOOGLE_AUTH_FAILED`: unpublish, reconnect the credential, verify every
  Sheets-node binding, and require a successful manual run;
- `GOOGLE_SCHEMA_MISMATCH`: unpublish, compare canonical headers, repair
  deliberately, and never auto-rewrite the workbook;
- `SNAPSHOT_VALIDATION_FAILED`: unpublish and investigate the bridge/upstream
  contract without accepting a suspicious empty portfolio;
- `WRITE_FAILED` or `WORKFLOW_TIMEOUT`: unpublish, identify the last completed
  write, preserve all rows, repair, and rerun the same business date;
- `GOOGLE_RATE_LIMITED` or `GOOGLE_TEMPORARY_FAILURE`: let bounded retries end,
  then unpublish if the execution failed, wait for recovery, and run manually.

`SUCCESS_WITH_WARNINGS` is not automatically a failure. Expected categories
include incomplete liability coverage, partial known-EUR analytical coverage,
and understood configured count or net-worth movement thresholds. Investigate
any other category before leaving the schedule active.

### Routine monitoring and staleness

After a scheduled execution inspect the n8n result and terminal `sync_runs` row:
status, `liability_coverage`, `warning_count`, newest successful completion,
unexpected account/position count movement, duration, and `error_code` on
failure. Raw node payloads are needed only for controlled diagnosis.

Treat synchronization as stale when no `SUCCESS` or `SUCCESS_WITH_WARNINGS` has
completed for more than 48 hours while the host is expected to be online. Do
not fabricate portfolio updates during a stale period; inspect service health,
authentication, Google access, execution state, and telemetry instead.

## Failure recovery

### Finary authentication or MFA

Phase 8 accepts only the minimum verified Clerk restart state: the session ID
and production `__client` cookie. Compose stores them in the bridge-only
`finary_session_data` volume as versioned JSON under `0700` directory and
`0600` file permissions. The state is bearer-equivalent while valid. It must
never reach n8n, Sheets, ChatGPT, Git, logs, workflow exports, or backups.
Bearer JWTs remain in memory; TOTP secrets, backup codes, and one-time codes
must never be persisted. Authentication failure must leave all portfolio
sheets unchanged.

Normal startup remains lazy: start the bridge without authenticating and verify
`/health`. This proves only process readiness. Do not publish or activate the
daily workflow.

If the protected store is empty, expired, or revoked, bootstrap it once with a
current one-time code. Recreate the bridge, make an authenticated request
promptly, then remove the code from the shell environment:

```bash
read -s "FINARY_MFA_CODE?Enter the current Finary TOTP code: "
echo
export FINARY_MFA_CODE
docker compose up -d --force-recreate finary-bridge
unset FINARY_MFA_CODE
```

The first successful `/v2/snapshot` request stores only the allowed Clerk
state. Recreate the bridge again without `FINARY_MFA_CODE` and repeat the
request; the protected session should refresh without prompting. `/health`
proves process readiness only and never touches the session file.

For diagnostics, `/health` proves only that the bridge process is ready and
never contacts Finary. Call `/v2/snapshot` with the configured API key to verify
the canonical coverage-aware path; current structure should be HTTP 200 with
`coverage.liabilities = UNAVAILABLE`, null liability/net-worth totals, and no
authoritative liability records. Do not print asset values in shared logs.

To repeat the sanitized adapter investigation deliberately, run from
`finary-bridge` with local credentials and interactive MFA available:

```bash
FINARY_LIVE_TEST=1 FINARY_LIVE_DESCRIBE=1 \
  python -m pytest -m live tests/live/test_finary_live.py -vv -s --tb=no
```

The liability diagnostic must report `UNAVAILABLE` for the current adapter. It
prints no endpoint payload, value, ID, account name,
institution, address, token, cookie, or MFA value. A successful authentication
and empty nested `loans` arrays do not alter the conclusion. Operators must not
create zero liability rows, calculate net worth, clear prior liabilities, or
publish the daily schedule from that observation.

To repeat the Phase 8 restart test, first configure an absolute empty
`FINARY_SESSION_PATH` outside the repository, then run:

```bash
FINARY_LIVE_SESSION_TEST=1 \
  python -m pytest -m live tests/live/test_finary_session_live.py -vv -s --tb=no
```

It prompts for one factor, then verifies two fresh clients without another
factor and prints sanitized status only. The 2026-08-21 acceptance run also
verified the same state from an independent Python process. Production live
acceptance additionally proved repeated refreshes in one long-lived adapter;
the adapter creates a fresh private HTTP session at each refresh boundary while
retaining its process-wide lock. It never prints
cookies, tokens, session identifiers, factors, identities, or portfolio values.

Expiry and revocation are terminal for the persisted session. A definitive
refresh rejection clears local state and returns sanitized
`FINARY_AUTH_FAILED`; a fresh manual bootstrap is then required. Temporary
network/service failures preserve the prior state for a later bounded request.
Password and MFA changes are not assumed to revoke every existing session:
explicitly sign out/revoke upstream sessions and clear the local state during
rotation or suspected compromise.

To clear the Compose store without displaying it:

```bash
docker compose stop finary-bridge
docker compose run --rm finary-bridge \
  python -c 'import os; from app.finary_session_store import FileFinarySessionStore; FileFinarySessionStore(os.environ["FINARY_SESSION_PATH"]).clear()'
```

Clearing local state does not revoke a stolen copy. Use Finary's sign-out-all
or session controls as well, then restart and bootstrap with MFA.

### Google authentication

Reconnect or rotate the OAuth credential in n8n, assign it to every Sheets node
in both workflows, and execute manually. Never export OAuth credentials with a
workflow.

### Rate limiting or temporary Google errors

Wait for the quota window to reset, confirm every read node has `Execute Once`,
then retry manually. Re-running is idempotent: current rows and same-day rows use
deterministic keys. Do not clear sheets before retrying.

### Header/schema drift

Stop runs. Compare row 1 of every sheet with
`docs/google-sheets-schema.json`, repair headers and order, then rerun manually.
Do not modify manual-sheet data or replace blanks with zero.

### Partial write or timeout

Leave existing rows in place. Inspect the failed node, correct the dependency,
and rerun the same business day. Append-or-update keys repair current and
same-day state without deleting history. Review `sync_runs` and all affected
sheets before considering activation.

Use this decision tree: if no portfolio write node ran, fix the cause and rerun;
if any write node ran, record the last completed node, do not edit or clear
automated sheets, fix the dependency, and rerun the same business day; then
verify deterministic current keys, same-day history/daily keys, inactive flags,
and one terminal telemetry row. Escalate rather than activating the schedule if
the repaired run produces different deterministic keys or unexplained totals.

## Backup and restore

Create a fresh production checkpoint before n8n upgrades, encryption-key
rotation, major workflow/schema migration, or any risky recovery operation.
The checkpoint must include the complete `n8n_data` volume, the exact matching
`N8N_ENCRYPTION_KEY` preserved separately, and a private canonical-workbook
copy/export. Verify an owner-only archive and SHA-256 checksum. Do not back up
`finary_session_data`; a disaster-recovered bridge requires a fresh MFA
bootstrap.

Before those operations:

1. Stop n8n: `docker compose stop n8n`.
2. Back up the `n8n_data` named volume with a trusted local Docker-volume backup
   procedure and store it encrypted.
3. Export both workflows from n8n and verify the exports contain no credential
   objects.
4. In Google Drive, create a private copy of the canonical workbook or export
   it to an owner-only encrypted location. Verify the copy contains all ten
   tabs, current/history data, telemetry, and manual sheets. It contains
   financial data and must not be committed or broadly shared.
5. Preserve the exact `N8N_ENCRYPTION_KEY` separately in a secret manager. A
   volume backup without that key cannot decrypt stored credentials.

Use this safe local-volume procedure for n8n migration or disaster-recovery
preparation:

1. Record the source container, image digest, mounts, network, localhost port,
   workflow activation state, error-workflow linkage, and execution count.
2. Confirm the ignored environment uses the exact live encryption key and
   canonical workbook identifier without printing either value.
3. Stop n8n cleanly. Do not remove its container or source volume.
4. Archive the full mounted n8n data directory into an owner-only directory on
   an encrypted local volume. Set the directory to `0700`, the archive and
   checksum to `0600`, and verify the SHA-256 checksum.
5. Restore the archive into a new temporary Docker volume. Start an isolated
   n8n with no network and no published port, using the matching encryption
   key. Confirm the owner setup, workflow list, execution telemetry, and a
   successful decrypted credential export.
6. Destroy only that temporary verification instance after it passes. Keep the
   protected archive and original source volume.
7. Restore into an empty Compose-managed `n8n_data` volume while n8n is stopped,
   then start the full stack and perform the topology and persistence checks.

Never copy only `database.sqlite`: n8n state can include additional files and
SQLite sidecars. Never restore over a running n8n instance. Never print a
decrypted credential export or include it in the backup archive.

Do **not** back up `finary_session_data`. It contains bearer-equivalent Clerk
state and is intentionally recoverable only by a fresh MFA bootstrap after a
host loss. Do not include it in generic Docker-volume backup jobs.

To restore, create an empty replacement volume, restore the backup while n8n is
stopped, provide the original encryption key, start the stack, and verify both
workflows and credentials before any manual execution. Restore the workbook
only into a controlled copy first, then point `FINARY_GOOGLE_SHEET_ID` at the
verified target.

After restore, run one full persistence cycle without deleting volumes:

```bash
docker compose down
docker compose up -d --build
```

Verify health, internal bridge/schema reachability, the owner account,
decryptable Google credential, both workflows and their linkage, retained
execution history, and the inactive daily schedule. Confirm `/v2/snapshot`
still reuses the protected bridge session without an interactive HTTP prompt.
Only then may obsolete containers be removed. Retain the source volume and
protected archive until the operator explicitly ends the rollback window.

For host disaster recovery, restore `n8n_data` and the private canonical
workbook first, provide the original `N8N_ENCRYPTION_KEY`, and start Compose.
Reconnect a Google credential only when the preserved credential genuinely
cannot be used; do not overwrite it to hide an encryption-key mismatch. Because
`finary_session_data` is intentionally absent from disaster-recovery backups,
perform a fresh transient MFA bootstrap. Keep the daily workflow inactive until
the restored owner, credential, workflows, history, schema, snapshot, workbook,
and idempotency checks all pass manually.

Canonical production restore acceptance is deliberately inactive-first:

1. unpublish the daily workflow or keep the restored copy unpublished;
2. stop n8n and restore the complete archive into an empty replacement volume;
3. provide the matching encryption key and start Compose;
4. verify owner state, credential decryptability, workflows, linkage, and
   execution history;
5. restore or verify the private workbook where necessary;
6. perform a fresh transient Finary MFA bootstrap because Clerk state is not
   backed up;
7. run one successful manual synchronization and validate deterministic state;
8. only then publish the single canonical daily workflow again.

Never restore production state directly into an active scheduler.

## Rotation and upgrades

- Finary password: explicitly sign out/revoke upstream sessions, stop the
  bridge, clear its session store, update the ignored environment, recreate the
  bridge, and complete a new manual factor challenge. Password change alone is
  not assumed to revoke every existing Clerk session.
- Finary MFA factor: explicitly sign out/revoke upstream sessions, clear the
  bridge store, rotate the factor in Finary, discard any pending one-time code,
  and bootstrap with the new factor. Never copy the TOTP seed or backup codes
  into bridge configuration.
- Bridge API key: rotate the same value in bridge and n8n environments, recreate
  both services, and verify `/health` plus a manual structured snapshot call.
- Google OAuth: reconnect inside n8n and reassign every Sheets node.
- n8n encryption key: use n8n's supported key-rotation/migration procedure; do
  not simply replace it while encrypted credentials exist.
- n8n/image upgrades: back up first, pin the reviewed image digest, import-test
  both workflows in an isolated instance, run the repository tests and Compose
  validation, then perform one inactive manual run.

Never use `docker compose down -v` during routine operations: it deletes both
the persistent n8n state and the protected Clerk session volume.
