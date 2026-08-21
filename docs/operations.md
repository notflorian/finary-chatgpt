# Operations runbook

This runbook covers the local Phase 6 stack: `finary-bridge`, n8n, the local
canonical-schema service, Google Sheets, and the two importable workflows. It
does not change the Phase 5 synchronization semantics.

## Safety state

Keep `Finary - Daily Sync` **inactive** in production. The live adapter still
returns `FINARY_FEATURE_UNAVAILABLE` because liability coverage is unverified.
That structured failure is expected and must not overwrite the last valid
current portfolio state. Enable the schedule only after the bridge can produce
a complete snapshot and a manual run has been reviewed.

The activation path is tracked in GitHub: liability completeness
[#13](https://github.com/notflorian/finary-chatgpt/issues/13) and unattended
authentication [#14](https://github.com/notflorian/finary-chatgpt/issues/14)
block live acceptance [#15](https://github.com/notflorian/finary-chatgpt/issues/15).
Compose migration [#16](https://github.com/notflorian/finary-chatgpt/issues/16)
and CI [#17](https://github.com/notflorian/finary-chatgpt/issues/17) are also
required before production activation
[#18](https://github.com/notflorian/finary-chatgpt/issues/18). ChatGPT connection
[#19](https://github.com/notflorian/finary-chatgpt/issues/19) follows only after
activation has produced a validated workbook state.

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

The n8n database and encrypted credentials persist in the named `n8n_data`
volume. The Compose ports bind to localhost only. The schema service has no
host port and mounts the canonical JSON read-only.

Open n8n at `http://127.0.0.1:5678`. View bounded recent logs with
`docker compose logs --tail=200 finary-bridge n8n schema-server`; review them
before sharing because execution detail can contain private node input. Routine
lifecycle commands are `docker compose build`, `docker compose up -d`, and
`docker compose down` without `-v`.

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

## Failure recovery

### Finary authentication or MFA

The bridge keeps Clerk session data in memory only. A fresh container can need
a new prepared TOTP/email challenge. Put the current one-time code in the local
environment only, recreate `finary-bridge`, verify `/health`, run once, then
remove the code from the shell/environment file. Never persist Clerk cookies,
tokens, backup codes, or TOTP secrets. Authentication failure must leave all
portfolio sheets unchanged.

Live verification confirmed that interactive authentication succeeds when the
TOTP is requested after Clerk returns its challenge. The HTTP bridge cannot
prompt, so its code must be preloaded: wait for a newly rotated TOTP, recreate
the bridge immediately, and start the manual workflow within the same validity
window. A healthy `/health` response does not prove that a preloaded TOTP is
still valid. An expired code produces the sanitized `FINARY_AUTH_FAILED` result
and must not trigger portfolio writes.

For diagnostics, `/health` proves only that the bridge process is ready and
never contacts Finary. Call `/v1/snapshot` manually with the configured API key
to test the upstream path; expect the current sanitized
`FINARY_FEATURE_UNAVAILABLE` response until liability coverage is verified.

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

Before upgrades or credential rotation:

1. Stop n8n: `docker compose stop n8n`.
2. Back up the `n8n_data` named volume with a trusted local Docker-volume backup
   procedure and store it encrypted.
3. Export both workflows from n8n and verify the exports contain no credential
   objects.
4. Export the Google workbook to a protected location. It contains financial
   data and must not be committed.
5. Preserve the exact `N8N_ENCRYPTION_KEY` separately in a secret manager. A
   volume backup without that key cannot decrypt stored credentials.

To restore, create an empty replacement volume, restore the backup while n8n is
stopped, provide the original encryption key, start the stack, and verify both
workflows and credentials before any manual execution. Restore the workbook
only into a controlled copy first, then point `FINARY_GOOGLE_SHEET_ID` at the
verified target.

## Rotation and upgrades

- Finary password: update the ignored environment, recreate only the bridge,
  and manually verify authentication.
- Bridge API key: rotate the same value in bridge and n8n environments, recreate
  both services, and verify `/health` plus a manual structured snapshot call.
- Google OAuth: reconnect inside n8n and reassign every Sheets node.
- n8n encryption key: use n8n's supported key-rotation/migration procedure; do
  not simply replace it while encrypted credentials exist.
- n8n/image upgrades: back up first, pin the reviewed image digest, import-test
  both workflows in an isolated instance, run the repository tests and Compose
  validation, then perform one inactive manual run.

Never use `docker compose down -v` during routine operations: it deletes the
persistent n8n volume.
