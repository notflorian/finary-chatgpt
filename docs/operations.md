# Operations

One local stack owns one official-MCP connection, one writer and one fresh
workbook. Follow this sequence from a clean checkout. Installation creates a new
workbook; it supplies no conversion or relabeling of existing data. The repository
workflow exports are inactive for safe import.

## Guided fresh installation

Follow the numbered path from a clean checkout. Each authorization is separate:
local health, OAuth-state placement, Google credential binding, successful
synchronization, and validated readback prove different things.

### 1. Verify prerequisites and host boundary

**Where:** repository-root terminal, local browser, and Google Cloud.

Before creating a virtual environment, verify Git, Compose, the running Docker
daemon, and the specific Python command to use. Do not assume stock `python3`
meets the version requirement:

```bash
git --version
docker compose version
docker info >/dev/null
python3.12 --version
```

Choose an interpreter reporting Python 3.12 or newer; substitute its command for
`python3.12` below. You also need a local browser, official Finary MCP access, a
Google account, and Google Cloud permission to enable Sheets and Drive APIs and
create a Web OAuth client. Continue only when Docker responds successfully.

Host OAuth uses POSIX locking. Native Windows Python is unsupported. The handoff
is regression-tested on rootful Linux Docker without user-namespace remapping;
macOS, rootless Docker, user namespaces, and WSL are not certified by that
evidence and have different ownership semantics.

### 2. Install the operator tools and create private configuration

**Where:** repository-root terminal. Create private `.env` before starting the
stack:

```bash
python3.12 -m venv finary-bridge/.venv
source finary-bridge/.venv/bin/activate
python -m pip install ./finary-bridge
umask 077
cp -n .env.example .env
chmod 600 .env
export COMPOSE_PROJECT_NAME=finary-chatgpt
```

Keep this environment active for repository scripts. Review `.env` locally; do
not print its contents or resolved Compose configuration. Set a strong, stable
`N8N_ENCRYPTION_KEY` and optionally `FINARY_BRIDGE_API_KEY` using a local password
manager. The bridge and n8n receive the same API key. Keep the stock state path
`/var/lib/finary-mcp/state/oauth.json`, localhost ports and one production writer.
Record the checked-out Git commit and image pins privately. Install from matching
source/contracts, not from a tag selected solely by its version label. Keep the
Compose project for handoff, startup, and later configuration: retain this export
in the terminal or save `COMPOSE_PROJECT_NAME=finary-chatgpt` in private `.env`.
Exported values override `.env`.

### 3. Authorize Finary on the host

**Where:** repository-root terminal and local browser. This is explicit operator
consent, not an assistant/plugin grant.

#### Independent MCP OAuth

Create a new private staging directory outside the checkout and run explicit
operator consent on the host:

```bash
umask 077
export MCP_BOOTSTRAP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/finary-mcp-bootstrap.XXXXXX")"
python -m app.mcp_auth bootstrap --state "$MCP_BOOTSTRAP_DIR/oauth.json"
```

Bootstrap opens a browser and binds `127.0.0.1:8765/callback`; keep that port free.
It verifies issuer `https://clerk.finary.com` and allowlisted endpoints, using
public-client registration and authorization code + S256 through the pinned SDK.
Never reuse an assistant/plugin grant. The preference `openid profile email
offline_access` does not prove the actual requested/granted scopes: the SDK uses
the challenge and metadata. Effective scopes are not a certified minimum set.
Unsupported consent returns `MCP_AUTH_UNAVAILABLE`, without invented endpoints.

Bootstrap `--diagnose` prints fixed stage names/status codes, never tokens or
OAuth bodies. It remains an explicit consent attempt. See
[diagnostics](development.md#opt-in-diagnostics) for separately authorized
isolated checks, including the operator UID/GID configuration and exclusive
host/container handoff.

### 4. Hand off the authorized state

**Where:** repository-root terminal. Finish bootstrap and stop all users of its
state before continuing.

Finish the host bootstrap and stop all users of its state. The host command
requires POSIX file locking. The production-volume handoff is regression-tested
on rootful Linux Docker without user-namespace remapping; native Windows Python
is unsupported, and macOS, rootless Docker and user namespaces are not certified
by that Linux ownership evidence.

Choose the Compose project that will own the installation. The example runs from
the repository root; the helper itself resolves repository and Compose paths from
its installed script location rather than the caller's working directory. Keep
`COMPOSE_PROJECT_NAME` exported for the later Compose commands.
`--cleanup-source` requests removal of the designated
`finary-mcp-bootstrap.*` staging directory only after destination verification;
omit it to retain the staging copy for separate operator cleanup.

```bash
export COMPOSE_PROJECT_NAME=finary-chatgpt
python scripts/handoff-mcp-oauth-state.py \
  --source "$MCP_BOOTSTRAP_DIR/oauth.json" \
  --project-name "$COMPOSE_PROJECT_NAME" \
  --cleanup-source && unset MCP_BOOTSTRAP_DIR
```

Success is one JSON object with `status: OAUTH_STATE_HANDOFF_VERIFIED`,
`bridge: STOPPED`, `renewable_state: true`, `generation_match: true`, and the
requested cleanup outcome. The helper validates the existing private source
before mutation, holds its existing OAuth lease during transfer, targets the
stock bridge-only named volume, runs transfer and verification containers with
no network, and preserves the exact state generation and bytes under root-owned
0700/0600 paths. It does not start the bridge, n8n or synchronization.

An existing destination state directory is always refused. If transfer or
verification is interrupted, retain the original staging state, keep the bridge
stopped, and inspect both locations; do not delete the partial volume or rerun
the helper over it. A cleanup failure is reported separately as verified
destination plus failed cleanup—inspect only the designated staging directory
instead of repeating the handoff. Cleanup begins only after the source lease is
held continuously through transfer and verification; it revalidates the exact
source while holding both source locks, then removes only the state and known
coordination files while those locks remain held. The operating model still
requires one owner and does not provide an atomic host-to-Docker transaction.
Never revoke the grant merely to remove staging files, and do not back up
renewable state.

This verifies local placement and preserved renewable-state structure only.
`live_validity` remains unverified: successful handoff does not prove current
consent validity, refresh success or connectivity.

### 5. Start the stack and authorize Google

**Where:** repository-root terminal, Google Cloud, browser, and n8n.

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
create a Web application OAuth client. Before connecting, choose how this Google
OAuth app will be used:

- For temporary evaluation, an **External** app in **Testing** can authorize
  listed test users, but its refresh tokens expire after seven days. The pinned
  [n8n 2.35.5 Sheets credential](https://github.com/n8n-io/n8n/blob/n8n%402.35.5/packages/nodes-base/credentials/GoogleSheetsOAuth2Api.credentials.ts)
  requests Sheets and Drive scopes, so Google's identity-only exception does not
  apply. Expect to reconnect the credential; a successful first run does not
  establish unattended access.
- For sustained use with a personal Google account, use an **External** app with
  publishing status **In production**, subject to Google's
  [audience, verification and account-policy conditions](https://support.google.com/cloud/answer/15549945)
  and [personal-use verification rules](https://support.google.com/cloud/answer/13464323).
  An eligible Google Workspace organization can instead use an **Internal** app
  limited to its members, subject to administrator policies. Neither choice
  guarantees that a grant will never expire or be revoked; see Google's
  [refresh-token expiration rules](https://developers.google.com/identity/protocols/oauth2#expiration).

If you already connected while the app was in Testing, review its configuration
and reconnect the n8n credential before relying on an unattended schedule.

In n8n 2.35.5, create a Google Sheets OAuth2 credential. Register the **exact
callback URL displayed by n8n** on that Google client—Google requires an exact
redirect URI match—then enter its client ID/secret and connect your account with
explicit consent. See [Google's consent-screen guidance](https://developers.google.com/workspace/guides/configure-oauth-consent)
and [redirect-URI rule](https://developers.google.com/identity/protocols/oauth2/web-server#redirect-uri).
Publishing the External Google OAuth app sets its publishing status; it does
not share the workbook or publish the n8n workflow. Use the credential only in
this n8n instance, keep the workbook private, and keep the stack on localhost.
Google authorization is independent of Finary OAuth and ChatGPT's Drive access.

### 6. Create and activate a fresh workbook

**Where:** repository-root terminal, n8n, Sheets, then `.env`.

#### Fresh workbook initialization

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
   credential created above.
3. Enable **Send Body**, set **Body Content Type → JSON**, then
   **Specify Body → Using JSON**. Paste the complete generated object into the
   **JSON** field in fixed-value mode, including its outer braces.
4. Under **Options → Response**, set **Response Format → JSON** and leave
   **Include Response Headers and Status** off.
5. Execute once. Open the HTTP Request node's **Output → JSON** and record
   `spreadsheetId` and `spreadsheetUrl` from the returned item locally. The ID
   becomes `<new-workbook-id>` below.

This request creates a new workbook; it has no existing destination to clear.
If the response is lost, inspect Drive for the created workbook before repeating:
creation is not idempotent. Stop on partial/incompatible structure rather than
clearing or reshaping a populated workbook. Remove the temporary creation node
once the result is verified to prevent accidental repeat creation.

#### Configure writer and activate the workbook

Edit the repository-root `.env` file, replacing any existing entries below with
the new workbook and the exact initializer values. Save the file; pasting these
assignments into a terminal does not update `.env`:

```dotenv
FINARY_MCP_GOOGLE_SHEET_ID=<new-workbook-id>
FINARY_MCP_SCHEMA_URL=http://schema-server/google-sheets-schema.json
FINARY_MCP_WRITER_ID=portfolio-writer
FINARY_MCP_WRITER_GENERATION=1
```

From the repository root, apply the changed environment:

```bash
docker compose up -d n8n
```

Compose recreates n8n when its effective environment changes. A container restart
alone does not apply new environment values.

Keep settings in `.env` for later sessions. See
[configuration troubleshooting](#configuration-troubleshooting) if saved values
are not taking effect.

Compare every sheet/header and README entry against the generated inventory.
Verify exactly one `writer_control` row with workbook `1.0`, official provider, matching writer
ID and positive generation. Explicitly change only its state from `PAUSED` to
`ACTIVE`. This permits manual writes; it does not publish a schedule.

### 7. Prepare, import, and run the workflow

**Where:** repository-root terminal and the same n8n instance.

Create and authorize one **Google Sheets OAuth2 API** credential in the destination
n8n instance before importing the workflow. In n8n 2.35.5, open **Credentials**,
select that credential, and copy its identifier from the final path segment of the
credential editor URL (`/credentials/<credential-id>`). Record the credential
identifier and exact credential name before using the preparation command. They
are references, not OAuth secrets; do not export the credential or disclose OAuth
material.

Prepare a personalized, local import file outside this repository and every Git
worktree. The command reads only the canonical inactive export and changes only
Google Sheets credential references:

```bash
python scripts/prepare-n8n-workflow.py \
  --credential-id '<existing-n8n-credential-id>' \
  --credential-name '<exact-n8n-credential-name>' \
  --output /tmp/finary-mcp-sync-local.json
```

It configures every Google Sheets node, including preflight, control, terminal and
failure nodes, and reports the configured count without printing the credential.
It neither authenticates Google nor checks that the referenced credential exists
in n8n. It also never executes, uploads, activates, or publishes a workflow.
The output path must be new and external: an existing destination, a checkout, or
a symlink resolving into a checkout is rejected without modification. Keep the
generated file private and out of version control. Regenerate it if the credential
is recreated or if the target n8n instance changes.

Import `/tmp/finary-mcp-sync-local.json` into that same n8n instance and keep it
unpublished. Check the Google Sheets bindings before continuing. As a fallback,
import `n8n/workflows/finary-mcp-sync.json` and manually assign the same runtime
Google Sheets OAuth credential to **every Google Sheets node**. Never commit
credential bindings in an export. No separate error workflow or n8n API credential
is needed.

Run one full execution from **Manual Trigger**, with no cached or pinned node
outputs. Every required write must precede **Record MCP Success**. Empty batches
continue once without dummy rows. Complete empty holdings inactivate previous
positions; partial/unavailable detail cannot clear them. Already inactive rows
keep their original observation/timestamps without further writes.

In this completed execution, open **Record MCP Success → Input → JSON**.
Copy the terminal row's `run_id`, and confirm its `status` is `SUCCESS` or
`SUCCESS_WITH_WARNINGS`. In Sheets, confirm the same `run_id` and status in
`sync_runs`. Use that complete string for readback below, not the n8n execution
number from the browser URL.

Manual `allocation_targets`, `asset_overrides` and `cashflows` are never sync
write targets. All rows still need unique keys and typed literal values. Only
notes can contain formulas; allocation fractions must be ordered within 0–1.
Automated amounts/quantities remain exact decimal text with RAW writes; nulls
explicitly clear cells using empty strings. Known zero and false remain known.

### 8. Validate native readback, then publish and connect ChatGPT

**Where:** n8n, repository-root terminal, then ChatGPT.

#### Consumer readback verification

After writes settle, use a temporary unpublished HTTP Request node with the same
Google credential: method `GET`, URL
`https://sheets.googleapis.com/v4/spreadsheets/<workbook-id>`, query parameter
`includeGridData=true`, and no field/range filter. Keep **Send Body** off. Under
**Options → Response**, choose **Response Format → JSON** and leave
**Include Response Headers and Status** off. Execute once with no pinned data.

Open this node's **Output → JSON**, with no search or field selection. If n8n
hides the large result, use **Download** in that panel. For a displayed result,
use its **Copy to Clipboard** button with no JSON value selected and paste into
a local plain-text file. Save the complete export as
`/tmp/finary-workbook-items.json`; do not copy a visible preview by selecting text.
The download contains `[{"json": {"sheets": [...], ...}, ...}]`; the whole-output
clipboard copy contains `[{"sheets": [...], ...}]`. The checker accepts both
complete exports with `--input-format n8n`. These export shapes are defined by
the pinned
[download implementation](https://github.com/n8n-io/n8n/blob/n8n%402.35.5/packages/frontend/editor-ui/src/features/ndv/runData/components/RunData.vue)
and [JSON copy implementation](https://github.com/n8n-io/n8n/blob/n8n%402.35.5/packages/frontend/editor-ui/src/features/ndv/runData/components/RunDataJsonActions.vue).

The export contains private portfolio data. Keep it outside the repository and
backups unless covered by your private data policy. In the repository-root
terminal with the venv active, validate the saved export offline using the
completed execution's run ID:

```bash
chmod 600 /tmp/finary-workbook-items.json
python scripts/check-workbook.py --input-format n8n \
  --input /tmp/finary-workbook-items.json \
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

#### Scheduled synchronization and monitoring

Publish only after the manual run and full readback meet the intended coverage.
The schedule runs at 07:30 `Europe/Paris`; independently verify its first execution
with the same readback process. A successful state older than 48 hours is
operationally stale. A newer FAILED row does not replace valid success. Bank
freshness is independent of ingestion time. Connect ChatGPT using its
[private workbook setup](chatgpt.md#connect-the-workbook).

If the Google grant expires, [reconnect the existing Google Sheets OAuth2
credential in n8n](https://docs.n8n.io/integrations/builtin/credentials/google/oauth-single-service/#google-cloud-app-becoming-unauthorized)
with explicit Google consent. Rerun a manual synchronization and complete the
full workbook readback above before relying on the schedule again.

## Configuration troubleshooting

For temporary terminal-only configuration, export each writer variable before
running `docker compose up -d n8n` in that same terminal. Bare `NAME=value`
assignments are not passed to Compose unless already exported. Exported values
override `.env`; unset them before returning to the saved file. Keep the same
`COMPOSE_PROJECT_NAME` used for handoff and startup.

If **Initialize MCP Run** fails with `MCP_VALIDATION_FAILED` while validating
writer configuration, check that `FINARY_MCP_WRITER_ID` is nonempty and
`FINARY_MCP_WRITER_GENERATION` is an integer of at least 1 in n8n's environment.
Both must match the workbook's `writer_control` row. After correcting `.env`,
apply it with `docker compose up -d n8n` and retry from **Manual Trigger** without
cached or pinned outputs.

## Generated artifact adoption

Existing compatible workbooks need no migration or data edit. To adopt changed
artifacts, stop scheduled/manual executions, update bridge and reader from the
same commit, serve its matching schema, reimport its matching inactive workflow,
restore runtime credential binding, clear cached/pinned outputs, and authorize
execution separately. Do not mix artifacts from different commits, bypass the
digest, or initialize over an existing workbook.

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
