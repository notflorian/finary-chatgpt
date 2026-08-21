# Operations runbook

This runbook covers the local Phase 6 stack: `finary-bridge`, n8n, the local
canonical-schema service, Google Sheets, and the two importable workflows. It
does not change the Phase 5 synchronization semantics.

## Safety state

Keep the canonical daily workflow **inactive** until the production activation
gate is approved. Schema `2.0` returns truthful asset state with explicit
`PARTIAL`/`UNAVAILABLE` coverage. Phase 9 accepted its workbook and inactive
workflow end to end; no implementation step enables scheduling.

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
and CI [#17](https://github.com/notflorian/finary-chatgpt/issues/17) remain
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

Set `FINARY_GOOGLE_SHEET_ID` to the canonical schema-2.0 workbook, import the
two unsuffixed workflow exports, assign credentials to every Sheets node, and
link the error handler. The pre-production v1 workbook and workflows were
removed after live migration acceptance.

The n8n database and encrypted credentials persist in `n8n_data`. Sensitive
Clerk restart state persists separately in `finary_session_data`, mounted only
into the bridge. The Compose ports bind to localhost only. The schema service
has no host port and mounts the canonical JSON read-only.

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

Do **not** back up `finary_session_data`. It contains bearer-equivalent Clerk
state and is intentionally recoverable only by a fresh MFA bootstrap after a
host loss. Do not include it in generic Docker-volume backup jobs.

To restore, create an empty replacement volume, restore the backup while n8n is
stopped, provide the original encryption key, start the stack, and verify both
workflows and credentials before any manual execution. Restore the workbook
only into a controlled copy first, then point `FINARY_GOOGLE_SHEET_ID` at the
verified target.

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
