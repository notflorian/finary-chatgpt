# Operations

## Operating model

One stack owns one MCP workbook and one writer. Application 2.0.0 serves API
3.0 at `/v3/snapshot`; workbook layout 4.0 uses source contract 2.0.0.
The repository workflow exports are inactive for safe import. This release
requires a fresh workbook: it supplies no conversion from earlier workbooks,
including transitional layout 3.0. Existing operator data remains untouched.

## Independent MCP OAuth bootstrap

Install Python 3.12+ and the bridge as described in
[Development](development.md#local-environment). Follow
[independent OAuth](mcp-operations.md#backups-and-independent-oauth) on the host.
Never reuse an assistant/plugin grant. The verified issuer is
`https://clerk.finary.com`; routes and schedules never prompt for consent.
Keep renewable state in the bridge-only volume and access tokens in memory.
Google authorization is separate and belongs only to n8n/operator tooling.

Configure `.env` from `.env.example`, restrict it to mode 0600, and set a stable
`N8N_ENCRYPTION_KEY` and optional local `FINARY_BRIDGE_API_KEY`. After bootstrap,
with the host OAuth process stopped, transfer its protected directory once:

```bash
docker compose build finary-bridge
docker compose create finary-bridge
docker compose cp "$HOME/.local/state/finary-mcp-candidate" finary-bridge:/var/lib/finary-mcp/state
```

This command is for a fresh empty bridge volume. Do not replace existing state
or create concurrent owners. The supplied image runs as root; preserve directory
0700/file 0600 permissions. After startup and local status verification, remove
the host staging copy through your private operator procedure. Do not back it up.

## Fresh workbook initialization

Generate an offline, deterministic Google `spreadsheets.create` request from the
canonical schema. It contains all 19 sheets in their defined order, exact
headers, README metadata and one PAUSED control row. Automated and manual input
tables are empty. The generator needs no Finary authorization and never contacts
Google. It refuses to overwrite an existing output file.

```bash
python scripts/initialize-workbook.py --writer-id portfolio-writer --generation 1 \
  --output /private/tmp/finary-workbook-create.json
```

The default `--format google-create` is an executable API request body. Use
`--format inventory` for an offline inventory with explicit headers and rows.
To create the new workbook, an operator with independently obtained Google
Sheets authorization can apply the generated body once:

```bash
python - <<'PY'
import getpass
import json
from pathlib import Path
from urllib.request import Request, urlopen

payload = Path('/private/tmp/finary-workbook-create.json').read_bytes()
token = getpass.getpass('Independent Google access token: ')
request = Request('https://sheets.googleapis.com/v4/spreadsheets', data=payload,
                  headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
                  method='POST')
try:
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    print('New workbook ID:', result['spreadsheetId'])
except Exception:
    raise SystemExit('Creation outcome requires operator review; do not retry automatically.') from None
PY
```

This endpoint creates a new workbook and cannot clear or reshape an existing
target. There is no source/destination pair or historical/manual data conversion.
If the response is lost, stop and inspect Google Drive for the newly created
workbook before retrying; a second create request would create another empty
workbook. Never apply these sheets to a populated workbook. Preserve any operator
edits and stop on a partial/incompatible structure.

## Writer configuration and activation

Set these values in `.env` using the returned new workbook ID:

```dotenv
FINARY_MCP_GOOGLE_SHEET_ID=<new-workbook-id>
FINARY_MCP_SCHEMA_URL=http://schema-server/google-sheets-schema.json
FINARY_MCP_WRITER_ID=portfolio-writer
FINARY_MCP_WRITER_GENERATION=1
```

Keep one writer and exclude overlapping manual launches; production concurrency
is limited to one in Compose. Verify the README, ordered headers and singleton
`writer_control` row. Its workbook version, writer ID and positive generation
must match the configured values. After setup is verified, explicitly change
only `writer_control.state` from `PAUSED` to `ACTIVE`. This operator step permits
manual synchronization; it does not publish a schedule. Control rechecks detect
observed changes but are not an atomic lock or distributed compare-and-swap.

## Start, verify, and stop

```bash
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8000/health
```

Health returns application version 2.0.0 without upstream calls or OAuth-state
access. Bridge and n8n bind localhost; schema-server has no host port.
`restart: unless-stopped` recovers unexpected exits, while explicit operator
stops remain stopped. A health check reports health; it does not restart an
unhealthy running process. Inspect sanitized service logs and state before
restarting after persistent failure. `docker compose stop` preserves volumes.

## Inactive workflow import and manual synchronization

Open local n8n at `http://localhost:5678` and import
`n8n/workflows/finary-mcp-sync.json`. Keep it unpublished. Bind your runtime
Google Sheets OAuth credential to every Google Sheets node, including preflight,
control and failure nodes. There is no separate error workflow or n8n API
credential. Never save credential IDs in repository exports.

Start one full execution with **Manual Trigger**. Do not use cached partial
execution data or resume a saved execution from another n8n execution identity.
Inspect the full run: all required portfolio writes must precede **Record MCP
Success**. Empty batches skip their own writes and continue once. A complete
empty holdings observation inactivates prior positions, retains their original
identity/timestamps and writes no dummy/history holding. Partial/unavailable
holdings never clear valid current positions. Manual sheets are never write targets.
Sheets reads preserve formula text. Manual notes can retain formulas; fields used
for identity, classification and writer control must contain their declared
literal values. Automated monetary fields require exact decimal text, not formulas.

## Consumer/readback verification

After writes settle, read the entire native spreadsheet with
`includeGridData=true`, not formatted/truncated ranges. The production decoder
validates actual sheet order, exact headers, README and control. It accepts only
the current layout; no version alias or fallback serializer exists.
The operator can run this in the installed bridge environment:

```bash
python - <<'PY'
import getpass
import json
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen
from app.mcp_workbook import native_inventory, records
from app.mcp_consumer import observation, select, require

workbook_id = input('Workbook ID: ').strip()
expected_run = input('Run ID from the completed n8n execution: ').strip()
token = getpass.getpass('Independent Google access token: ')
url = 'https://sheets.googleapis.com/v4/spreadsheets/' + quote(workbook_id, safe='') + '?includeGridData=true'
try:
    request = Request(url, headers={'Authorization': 'Bearer ' + token})
    with urlopen(request, timeout=30) as response:
        inventory = native_inventory(json.load(response))
    book = records(inventory)
    terminals = [r for r in book['sync_runs'] if r['run_id'] == expected_run]
    require(len(terminals) == 1)
    now = datetime.now(timezone.utc)
    result = observation(inventory, terminals[0], now=now)
    latest = select(inventory, now=now)
    require(latest['context']['run_id'] == expected_run)
    require(result['current_complete'] and not result['dated_fallback'] and not result['stale'])
    print(json.dumps({'status': 'WORKBOOK_READBACK_VALIDATED', 'current_complete': True,
                      'series_break': latest['series_break']}))
except Exception:
    raise SystemExit('WORKBOOK_READBACK_REVIEW_REQUIRED') from None
PY
```

This structural acceptance example deliberately requires complete current detail.
A valid partial observation may still supply official totals; inspect its
independent coverage and dated limitations through the consumer without claiming
full detail acceptance. Sequential reads and writes are not atomic, even when
repeated reads agree. Retry the full read after writes settle if evidence conflicts.

## Scheduled synchronization and monitoring

Only after manual synchronization and readback succeed, publish the reviewed
workflow in n8n. Its schedule runs at 07:30 `Europe/Paris`. Verify the first
scheduled execution independently with the same consumer checks. A successful
state older than 48 hours is operationally stale. A later FAILED row does not
replace the newest validated success. Source bank freshness remains independent
of bridge collection time.

## Kill switch

Unpublish the workflow in n8n (CLI equivalent: `unpublish:workflow --id=<workflow-id>`).
Exclude manual launches, drain running/waiting/retrying executions and set
`writer_control.state` to `PAUSED`. Stop the bridge/n8n if necessary. Recheck
controls before reactivation. Never use `docker compose down -v` as routine recovery.

## Failure recovery

Malformed snapshots or prepared rows block the first portfolio write. Sheets
failures can leave partial physical state. In-graph failure telemetry is fixed,
sanitized and conditional on valid writer control and terminal headers. A hard
process loss may leave no terminal; absence of FAILED does not prove success.
A lost terminal response must never replace an already stored success with failure.

Pause and drain, inspect the failure, restore the correct current headers and
control without overwriting operator data, then start a full new execution.
Deterministic current keys repair interrupted writes. Accepted observations remain
immutable and distinct, including multiple observations on one business date.
Writer-generation changes or changed n8n execution identity block terminal success.
When replacing the designated writer, drain it first, increment the generation
and update both configuration and the control row while PAUSED.

OAuth recovery follows the independent runbook. Transient failures do not justify
new consent. Google credential failures are handled in n8n, never in the bridge.
Both HTTP calls and Sheets retries remain bounded. Do not weaken validation to
resume a run against an incompatible workbook.

## Backup and restore

Back up n8n state and its encryption key separately, plus the private workbook
according to the operator's data policy. Stop and drain n8n before copying its
SQLite state. Never back up renewable Finary OAuth state. Restore first into an
isolated unpublished stack with fresh independent OAuth and the current schema,
workflow and package. Do not mount production volumes in test containers.
Cancel saved/waiting executions; verify a full new manual run before publishing.
Reused n8n database execution numbers acquire a fresh UUID and cannot reuse an
old run identity. No reverse conversion to another workbook version is supplied.
