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
session from a terminal:

```bash
docker compose exec -e FINARY_MFA_CODE= finary-bridge python -c '
import getpass
from app.finary_client import FinaryApiClient

client = FinaryApiClient.from_environment(
    second_factor_code_provider=lambda strategy: getpass.getpass(
        f"Enter the one-time Finary {strategy} code: "
    )
)
client.authenticate()
client.get_accounts()
print("Persisted session bootstrap passed")
'
```

This writes only the verified session identifier and `__client` cookie to the
bridge-only volume. Bearer JWTs remain memory-only. The session file must remain
mode `0600`.

Verify a snapshot without printing its portfolio body:

```bash
curl --silent --output /dev/null --write-out '%{http_code}\n' \
  http://127.0.0.1:8000/v2/snapshot
```

Add `-H "X-API-Key: $FINARY_BRIDGE_API_KEY"` when the API key is enabled. A
successful HTTP 200 can legitimately report incomplete liability coverage.

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

Then run the bootstrap command again.

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
- counts match the current sheets;
- all current keys are unique;
- active positions reference an account;
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

Treat the newest parseable `completed_at` row whose status is `SUCCESS` or
`SUCCESS_WITH_WARNINGS` as the last valid synchronization. A later `FAILED` row
does not advance freshness. A last valid state older than 48 hours is stale and
requires investigation.

For a date, start with its single `portfolio_daily` row, require a matching
`sync_runs` row with status `SUCCESS` or `SUCCESS_WITH_WARNINGS` and a parseable
`completed_at`, then require exactly `positions_count` same-date history rows
with that `run_id` and unique position keys. A mismatch means that
non-transactional writes interrupted or superseded the state. Do not mix runs
or fall back silently; repair it with a successful manual rerun.

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
4. Clear rejected session state and perform a fresh interactive bootstrap.
5. call `/v2/snapshot` without printing its body;
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
3. verify manual sheets and last-known liability state were not altered;
4. fix the underlying credential, quota, or header problem;
5. start a full new workflow execution for the same logical date;
6. verify deterministic keys repaired rows without duplicates and that the
   successful run's history membership passes the count and daily-run checks;
7. verify one terminal telemetry row remains for the new run.

Do not delete current or historical rows as a recovery shortcut.

Sheets node retries configured inside a running execution retain its opaque
`n8n-execution:{execution_id}` identity and are idempotent. The n8n action that
retries a saved failed execution creates a new n8n execution but can reuse saved
node output containing the old identity. The workflow blocks terminal success
when it detects that mismatch. Use a full new workflow execution after a
partial-write failure. Retrying only `Record Successful Sync` is safe when the
execution had already completed every required portfolio write and reached that
final node.

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
  bridge, clear its session, bootstrap again, test manually, then republish.
- **Bridge API key:** update bridge and n8n environment together, recreate both
  containers, then verify a manual run.
- **Google OAuth:** reconnect in n8n and reassign every Sheets node before a
  manual run.
- **n8n encryption key:** follow n8n's supported key-rotation procedure. Do not
  simply replace the environment value; existing credentials would become
  unreadable.

After any rotation, inspect logs and `sync_runs` for sanitized output and ensure
no secret was copied into execution data or the workbook.
