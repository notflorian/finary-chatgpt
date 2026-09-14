# Operations

One local stack owns one official-MCP connection, one writer and one fresh
workbook. Follow this sequence from a clean checkout. Installation creates a new
workbook; it supplies no conversion or relabeling of existing data. The repository
workflow exports are inactive for safe import.

## Install and configure

Use Docker Compose, Git, Python 3.12+ and a local browser. Obtain access to the
official Finary MCP service and a Google account able to create private Sheets.
From the repository root:

```bash
python3 -m venv finary-bridge/.venv
source finary-bridge/.venv/bin/activate
python -m pip install ./finary-bridge
umask 077
cp -n .env.example .env
chmod 600 .env
```

Keep this environment active for repository scripts. Review `.env` locally; do
not print its contents or resolved Compose configuration. Set a strong, stable
`N8N_ENCRYPTION_KEY` and optionally `FINARY_BRIDGE_API_KEY` using a local password
manager. The bridge and n8n receive the same API key. Keep the stock state path
`/var/lib/finary-mcp/state/oauth.json`, localhost ports and one production writer.
Record the checked-out Git commit and image pins privately. Install from matching
source/contracts, not from a tag selected solely by its version label.

## Independent MCP OAuth

Create a new private staging directory outside the checkout and run explicit
operator consent on the host:

```bash
umask 077
export MCP_BOOTSTRAP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/finary-mcp-bootstrap.XXXXXX")"
python -m app.mcp_auth bootstrap --state "$MCP_BOOTSTRAP_DIR/oauth.json"
python -m app.mcp_auth status --state "$MCP_BOOTSTRAP_DIR/oauth.json"
```

Bootstrap opens a browser and binds `127.0.0.1:8765/callback`; keep that port free.
It verifies issuer `https://clerk.finary.com` and allowlisted endpoints, using
public-client registration and authorization code + S256 through the pinned SDK.
Never reuse an assistant/plugin grant. The preference `openid profile email
offline_access` does not prove the actual requested/granted scopes: the SDK uses
the challenge and metadata. Effective scopes are not a certified minimum set.
Unsupported consent returns `MCP_AUTH_UNAVAILABLE`, without invented endpoints.

`status` reads local state only and reports `live_validity: UNVERIFIED`; it does
not prove connectivity, consent validity or refresh success. Bootstrap
`--diagnose` prints fixed stage names/status codes, never tokens or OAuth bodies.
It remains an explicit consent attempt. See [diagnostics](development.md#opt-in-diagnostics)
for separately authorized isolated checks, including the operator UID/GID
configuration and exclusive host/container handoff.

## Place state in the bridge volume

Finish the host bootstrap and stop all users of its state. For a fresh, empty
bridge volume, run this block once from the repository root. It stops on any
error and refuses an already existing state directory:

```bash
(
  set -eu
  docker compose build finary-bridge
  docker compose create finary-bridge
  docker compose run --rm --no-deps -T finary-bridge python -c \
    "from pathlib import Path; Path('/var/lib/finary-mcp/state').mkdir(mode=0o700)"
  docker compose cp "$MCP_BOOTSTRAP_DIR/oauth.json" finary-bridge:/var/lib/finary-mcp/state/oauth.json
  docker compose run --rm --no-deps -T finary-bridge python -m app.mcp_auth status \
    --state /var/lib/finary-mcp/state/oauth.json
)
```

Do not rerun only the copy step against an existing destination. An interrupted
transfer requires inspection while the bridge remains stopped. The supplied
image runs as root; the destination directory/file must be root-owned and
0700/0600. `status` enforces these permissions. The volume is mounted only in the
bridge, never n8n. Access tokens remain memory-only.

After the destination status confirms the same nonempty generation as the host,
remove only the stopped staging copy and its lock files; never revoke the grant
as a way to remove the duplicate file:

```bash
python - <<'PY'
import os
from pathlib import Path
p = Path(os.environ['MCP_BOOTSTRAP_DIR'])
assert p.is_absolute() and not p.is_symlink() and p.name.startswith('finary-mcp-bootstrap.')
assert {f.name for f in p.iterdir()} <= {'oauth.json', 'oauth.json.lock', 'oauth.json.lease'}
for f in p.iterdir():
    assert f.is_file() and not f.is_symlink()
    f.unlink()
p.rmdir()
PY
unset MCP_BOOTSTRAP_DIR
```

This removes the staging files only. Do not back up renewable Finary state.

## Start the stack and authorize Google

```bash
docker compose up -d --build --wait
docker compose ps
curl --fail http://127.0.0.1:8000/health
```

Health returns `{"status":"ok","service":"finary-bridge","version":"1.0.0"}`
without upstream or OAuth-state access. Open `http://localhost:5678` and create
your local n8n account. The schema server has no host port.

In your Google Cloud project, enable the Google Sheets API and Google Drive API,
configure the OAuth consent audience/test users appropriate to your account, and
create a Web application OAuth client. In n8n, create a Google Sheets OAuth2
credential. Register the **exact callback URL displayed by n8n** on that Google
client, enter its client ID/secret into n8n and connect your Google account.
Use that credential only in this n8n instance; keep the workbook private.
Google authorization is independent of Finary OAuth and ChatGPT's Drive access.

## Fresh workbook initialization

Generate the complete offline Google `spreadsheets.create` body:

```bash
python scripts/initialize-workbook.py --writer-id portfolio-writer --generation 1 \
  --output /tmp/finary-workbook-create.json
```

The generator creates all 19 sheets in order, exact headers, current README
metadata, empty automated/manual tables and one PAUSED `writer_control` row.
It needs no Finary or Google authorization and refuses to overwrite the output.
`--format inventory` instead generates the corresponding offline inventory.

Apply the generated body through a temporary **unpublished** n8n workflow with a
Manual Trigger and an HTTP Request node:

1. Set method `POST`, URL `https://sheets.googleapis.com/v4/spreadsheets`.
2. Use **Predefined Credential Type → Google Sheets OAuth2 API**, selecting the
   credential created above. Send a JSON body containing the complete generated
   JSON object, not a quoted string. Request a JSON response.
3. Execute once and record the returned `spreadsheetId` and workbook URL locally.

This request creates a new workbook; it has no existing destination to clear.
If the response is lost, inspect Drive for the created workbook before repeating:
creation is not idempotent. Stop on partial/incompatible structure rather than
clearing or reshaping a populated workbook. Remove the temporary creation node
once the result is verified to prevent accidental repeat creation.

## Writer configuration and activation

Set `.env` to the new workbook and the exact initializer values:

```dotenv
FINARY_MCP_GOOGLE_SHEET_ID=<new-workbook-id>
FINARY_MCP_SCHEMA_URL=http://schema-server/google-sheets-schema.json
FINARY_MCP_WRITER_ID=portfolio-writer
FINARY_MCP_WRITER_GENERATION=1
```

Run `docker compose up -d n8n` to apply the changed environment. Compare every
sheet/header and README entry against the generated inventory. Verify exactly
one `writer_control` row with workbook `1.0`, official provider, matching writer
ID and positive generation. Explicitly change only its state from `PAUSED` to
`ACTIVE`. This permits manual writes; it does not publish a schedule.

## Import and first manual synchronization

Import `n8n/workflows/finary-mcp-sync.json` into n8n and keep it unpublished.
Assign the runtime Google Sheets OAuth credential to **every Google Sheets node**,
including preflight, control, terminal and failure nodes. Never commit credential
bindings in an export. No separate error workflow or n8n API credential is needed.

Run one full execution from **Manual Trigger**, with no cached or pinned node
outputs. Every required write must precede **Record MCP Success**. Empty batches
continue once without dummy rows. Complete empty holdings inactivate previous
positions; partial/unavailable detail cannot clear them. Already inactive rows
keep their original observation/timestamps without further writes.

Manual `allocation_targets`, `asset_overrides` and `cashflows` are never sync
write targets. All rows still need unique keys and typed literal values. Only
notes can contain formulas; allocation fractions must be ordered within 0–1.
Automated amounts/quantities remain exact decimal text with RAW writes; nulls
explicitly clear cells using empty strings. Known zero and false remain known.

## Consumer readback verification

After writes settle, use a temporary unpublished HTTP Request node with the same
Google credential: method `GET`, URL
`https://sheets.googleapis.com/v4/spreadsheets/<workbook-id>`, query parameter
`includeGridData=true`, JSON response, and no field/range filter. Save the complete
response object locally as `/tmp/finary-workbook-readback.json` with permissions
0600. Save the actual object containing `sheets`, not an n8n item array or preview.
It contains private portfolio data; keep it outside the repository and backups
unless explicitly covered by your private data policy.

Validate it offline using the completed execution's run ID:

```bash
python scripts/check-workbook.py --input /tmp/finary-workbook-readback.json \
  --run-id '<run-id-from-Record-MCP-Success>'
```

`WORKBOOK_READBACK_VALIDATED` requires that exact newest successful observation,
complete current detail and freshness. `WORKBOOK_READBACK_QUALIFIED` means a
valid dated/partial/stale result; inspect its limitations before deciding use.
`WORKBOOK_READBACK_REVIEW_REQUIRED` means validation failed. Diagnostics print
only fixed status/boolean fields, never portfolio values or credentials.
The [reading rules](chatgpt.md#reading-an-observation) explain interpretation.
Sequential reads and writes are not atomic; retry a full read after writes settle
if evidence conflicts. Matching repeat reads do not prove a transaction.

## Scheduled synchronization and monitoring

Publish only after the manual run and full readback meet the intended coverage.
The schedule runs at 07:30 `Europe/Paris`; independently verify its first execution
with the same readback process. A successful state older than 48 hours is
operationally stale. A newer FAILED row does not replace valid success. Bank
freshness is independent of ingestion time. Connect ChatGPT using its
[private workbook setup](chatgpt.md#connect-the-workbook).

## Stop and recover

Unpublish the workflow (CLI: `unpublish:workflow --id=<workflow-id>`), exclude
manual launches, drain running/waiting/retrying executions and set control to
PAUSED. `docker compose stop` preserves volumes. Never use `docker compose down -v`
as routine recovery. Keep one writer; control rechecks are not an atomic lock.

Malformed inputs block portfolio writes. Interrupted Sheets writes with a valid
matching FAILED terminal can recover through a full new execution. A hard process
loss may leave rows without terminal evidence: both reads and new writes then
stop. Preserve the workbook for investigation; use fresh initialization if the
terminal evidence cannot be recovered. Never fabricate terminal records or
relabel retained observations. Lost terminal responses cannot overwrite stored
success. Changing execution identity or writer generation blocks success.

To replace a writer, drain it, increment the generation and update configuration
and the control row while PAUSED. Resume with a new full execution, not saved
execution data. Health checks report health but do not restart unhealthy running
processes; `restart: unless-stopped` only handles process exits.

## OAuth lifecycle and recovery

Use one bridge process and one state on a local filesystem. Do not share the state
with host probes, replicated workers or another host. Session leases cover the
entire OAuth HTTP session; another owner waits about ten seconds then may fail
before HTTP. Short storage-lock contention can fail immediately. Let the owner
finish and retry; contention is not evidence of revoked consent.

The protected store retains registration metadata, refresh token, SDK-effective
scope and generation, not access tokens, callback state or PKCE secrets. Storage
format 1 does not retain scope provenance. CAS, atomic replacement and fsync
protect local writes. A crash between remote rotation and local persistence can
require explicit recovery. Do not edit or remove live state/lock files.

For persistent failures, pause and drain first, then stop the bridge and inspect
local state through an isolated one-shot process:

```bash
docker compose stop finary-bridge
docker compose run --rm --no-deps -T finary-bridge python -m app.mcp_auth status \
  --state /var/lib/finary-mcp/state/oauth.json
```
If replacement consent is needed, stop the bridge and authorize a new isolated
state explicitly. Use a fresh process to adopt it: CAS cannot invalidate an
already cached access token. Transient failures do not justify new consent.

Retiring a grant is a separate operator action. On the stopped owner's state,
`python -m app.mcp_auth revoke --state <absolute-path> --expected-generation <generation>`
requires its current status generation. Accepted revocation, local removal,
refresh rejection and access-token rejection are different outcomes. A retained
access token may remain usable until expiry; immediate remote invalidation and
indefinite consent are not guaranteed. General issuer context:
[Clerk revocation](https://clerk.com/docs/reference/backend/oauth-applications/revoke-token).

## Backup and restore

Back up stopped/drained n8n state and its encryption key separately. Keep private
native workbook backups that preserve manual values, formulas and protections.
Do not back up renewable Finary OAuth state. Rehearse restoration in an isolated,
unpublished stack with independent OAuth and matching current artifacts; never
mount production volumes in test containers. Preserve later operator edits before
any restore decision. Cancel saved/waiting executions and validate a fresh manual
run before publishing. Reused n8n execution numbers still need a new UUID.
