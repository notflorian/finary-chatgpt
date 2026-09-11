# Independent MCP candidate acceptance and cutover

This runbook is executable preparation for an operator. It does not authorize
production activation. The integration remains a candidate until independent
Finary consent, renewal, cold restart and isolated revocation, plus a separately
authorized shadow workbook, have been accepted. See the dated
[acceptance matrix](mcp-acceptance.md). Assistant/plugin authorization is unrelated
and must never be inspected, copied, revoked or used by these commands.

## Version and writer selection

| Provider | Bridge route | Workbook | Schema delivery | Workflow |
| --- | --- | --- | --- | --- |
| `private_api` (default) | `/v1/snapshot`, `/v2/snapshot` | 2.1 | `google-sheets-schema-v2.json` | `finary-daily-sync.json` and its legacy error handler |
| `finary_official_mcp` | `/v3/snapshot` | 3.0 | `google-sheets-schema.json` | `finary-mcp-sync.json`, with in-graph sanitized failure handling |

Set `FINARY_PROVIDER=finary_official_mcp` only for the candidate bridge. Local API
key authorization runs before either provider is constructed. The MCP provider
requires no private credentials. `/health` neither constructs a provider nor
reads authorization state. Legacy routes retain their binding and fail-safe
behavior. The optional `/v3/budget`, `/v3/spending-search` and `/v3/goals` are
protected read-only requests, independent of the scheduled portfolio path.

Set the candidate's distinct `FINARY_MCP_GOOGLE_SHEET_ID`, nonblank
`FINARY_MCP_WRITER_ID`, and positive `FINARY_MCP_WRITER_GENERATION`. The control row
must match all three version/provider/writer-generation constraints and be
`ACTIVE` before writes. A migrated copy starts `PAUSED`. Leave the legacy writer
on its original 2.1 workbook; neither writer silently accepts the other's schema.

## Backups and independent OAuth

1. Record deployed versions, workflow revisions, candidate/legacy workbook IDs,
   headers, row counts, manual edits and unresolved crosswalks in a private
   operator record. Do not put portfolio exports in the repository.
2. Back up n8n state and its encryption key separately using the existing
   [backup procedure](operations.md#backup-and-restore). Test restoration in an
   isolated environment. Never use production volumes in test containers.
   Preserve native Google workbook copies so formulas, formats, protections and
   manual notes survive. Do not use `docker compose down -v`.
3. Do not back up either renewable Finary store. Clerk and MCP have distinct
   bridge-only named volumes. The MCP store persists only client registration
   metadata needed by the SDK (`client_id`, issuer, redirect URIs and public
   token authentication method), a renewable refresh token, granted scope and a
   rotation generation. No bearer access token, authorization code, PKCE secret
   or callback state is persisted. Directory/file permissions are 0700/0600;
   writes are atomic with fsync, CAS generation checks and separate process
   leases. An old or failed refresh cannot delete a newer operator replacement.
4. For an isolated acceptance connection, use the local development environment
   on a machine with a browser. Use a fresh private directory, not an existing
   connection. From `finary-bridge`:

   ```bash
   umask 077
   mkdir -p "$HOME/.local/state/finary-mcp-candidate"
   python -m app.mcp_auth bootstrap --state "$HOME/.local/state/finary-mcp-candidate/oauth.json"
   python -m app.mcp_auth status --state "$HOME/.local/state/finary-mcp-candidate/oauth.json"
   ```

   The explicit bootstrap binds `127.0.0.1:8765/callback` and opens the metadata
   issuer's consent page. It requests the advertised `openid profile email
   offline_access` scopes with SDK authorization code + S256 and public-client
   dynamic registration. Server acceptance of registration/loopback/grants still
   needs real evidence. If unsupported, the command returns
   `MCP_AUTH_UNAVAILABLE`; do not invent endpoints or borrow assistant tokens.
   Routes and schedules never initiate consent or dynamic registration.

   If bootstrap fails before opening the browser, first run `status` against
   the same test state. An empty `generation` with `live_validity: UNVERIFIED`
   means the local store is readable but no client registration is persisted.
   Retry bootstrap with `--diagnose` to print fixed stage names and HTTP status
   codes only. This remains an explicit bootstrap attempt and can open consent;
   it never prints URLs, callback values, tokens, OAuth bodies or raw exceptions.
   Preserve the final allowlisted error code and stage for troubleshooting:

   ```bash
   python -m app.mcp_auth bootstrap --diagnose \
     --state "$HOME/.local/state/finary-mcp-candidate/oauth.json"
   ```

   The transport supplies an honest bridge `User-Agent` when an SDK-generated
   OAuth request has none. Public metadata checks on 2026-09-11 returned HTTP
   403 for SDK requests without this header and HTTP 200 with it, independently
   of the MCP revision header. This checks public discovery only; registration,
   consent and authenticated collection still need the operator's live evidence.
5. Status reports local restart-state presence and `live_validity: UNVERIFIED`;
   it is not a connectivity or consent assertion. Repeat a structural collection
   in a new process to prove cold restart, then separately exercise token expiry
   and renewal against isolated state. Never print amounts, IDs or token bodies:

   ```bash
   FINARY_MCP_LIVE_TEST=1 FINARY_MCP_LIVE_ISOLATED_STATE=1 \
   FINARY_MCP_LIVE_STATE_PATH="$HOME/.local/state/finary-mcp-candidate/oauth.json" \
   python -m pytest -q -s -m live tests/live/test_mcp_live.py
   ```

   Ordinary CI excludes this module. Structural success prints only a fixed
   status and negotiated protocol revision. It writes no workbook.

   If the structural test fails, repeat it with `FINARY_MCP_LIVE_DIAGNOSTICS=1`
   and `--tb=no`. The test observes the unchanged production calls and validators
   and prints only the tool name, failing boundary, allowlisted failure code,
   and bounded paths/missing-field names from the checked-in contract schema.
   It never prints instance paths, input values, remote schema contents or raw
   exceptions. A successful diagnostic run remains a normal validated collection.
6. Only after separately approving revocation of this **disposable** connection,
   get its current generation with `status` and run the explicit `revoke`
   command with `--state` and `--expected-generation`. Verify subsequent reads
   fail without consent. An HTTP-accepted revocation request alone does not prove
   all server-side access has ceased. Never run this against an existing user or
   assistant connection.

For eventual container use, bootstrap a new bridge-owned connection locally,
stop its users, and transfer its renewable state into the dedicated
`finary_mcp_data` volume using the operator's private file-copy procedure. Keep
only one renewable writer, preserve 0700/0600 permissions and set ownership to
the bridge process UID (the supplied image currently runs as root). Remove the
staging copy after verifying restart. Never put the state into `.env`, workflow
exports, n8n or a backup. A host bind mount can be selected in a private Compose
override instead, with the same single-writer and ownership requirements.

## Migration inventory, dry-run and candidate application

The migration tools never obtain Google credentials from n8n or an assistant.
The native command prompts for an independently supplied Google access token,
keeps it in memory and prints only fixed status. Run from the repository root
with the development virtualenv active. Use a private directory outside the
repository for every inventory and plan.

1. Pause old schedules and their error-handler delivery, drain running/retrying
   executions, and prevent new manual launches. Record the last validated 2.1
   run. Preserve the original workbook. Create a separate native Google copy as
   the candidate and keep a backup. Reconcile concurrent human edits before the
   inventory; a conflict is a stop condition, not permission to overwrite.
2. Inventory the source and save both typed inventory and complete native grid:

   ```bash
   python scripts/migrate-google-workbook.py inventory \
     --workbook "$LEGACY_WORKBOOK_ID" --output "$MIGRATION_DIR/source.json"
   cp "$MIGRATION_DIR/source.json" "$MIGRATION_DIR/verified-backup.json"
   python scripts/migrate-workbook.py inventory --source "$MIGRATION_DIR/source.json" \
     --output "$MIGRATION_DIR/inventory.json"
   ```

   The local backup copy protects the exact inventory; verify the separate
   native backup using Google before continuing. The native grid is saved as
   `source.native.json`. It contains private data and must stay private.
3. Produce the dated plan and a detached candidate without writing Google:

   ```bash
   python scripts/migrate-workbook.py plan --source "$MIGRATION_DIR/source.json" \
     --backup "$MIGRATION_DIR/verified-backup.json" \
     --destination-reference "$CANDIDATE_WORKBOOK_ID" --migration-id "$MIGRATION_ID" \
     --writer-id "$CANDIDATE_WRITER_ID" --changed-at "$MIGRATION_TIMESTAMP" \
     --output "$MIGRATION_DIR/plan.json"
   python scripts/migrate-workbook.py apply --source "$MIGRATION_DIR/source.json" \
     --plan "$MIGRATION_DIR/plan.json" --writers-drained \
     --output "$MIGRATION_DIR/candidate.json"
   python scripts/migrate-google-workbook.py requests --source "$MIGRATION_DIR/source.json" \
     --native-backup "$MIGRATION_DIR/source.native.json" --plan "$MIGRATION_DIR/plan.json" \
     --writers-drained --output "$MIGRATION_DIR/requests.json"
   ```

   Review IDs, digests, original cells and formats, appended headers, complete
   legacy history and manual sheets. Review unresolved crosswalks; do not apply
   legacy overrides automatically. The native planner compares the candidate
   against the source backup and emits only appended cell/column/table changes.
4. After candidate-write authorization, substitute `apply` for `requests` in the
   final command. This sends one bounded Google batch. A lost response triggers
   ledger re-reading, never blind re-addition of columns or sheets. Repeating
   the same validated plan is a no-op that preserves later manual changes;
   conflicting/interrupted ledgers require explicit reconciliation. Partial
   copies, conflicting reserved tab names, unsupported layouts or oversized plans
   fail closed. Additional user-owned grid tabs (for example charts) are bound
   into the source inventory and preserved in their original positions. No
   migration request writes those tabs. Their formulas, notes, formats and chart
   definitions must match the backup; calculated cell results are excluded from
   that comparison. A later edit is retained and requires reconciliation before
   migration replay.
5. Validate the detached result:

   ```bash
   python scripts/migrate-workbook.py verify --source "$MIGRATION_DIR/source.json" \
     --target "$MIGRATION_DIR/candidate.json" --plan "$MIGRATION_DIR/plan.json" \
     --output "$MIGRATION_DIR/validation.json"
   ```

   The native apply command also re-reads Google and checks the preserved cells,
   typed rows and validated ledger. No MCP observations are deleted on reruns.
   Same-day daily and holding-history rows include observation UUIDs; historical
   provenance absent in 2.1 remains blank/unknown in `legacy_observations`.

## Isolated acceptance, cutover and scheduling

Import the inactive candidate workflow and bind only its operator-approved
Google credential. Do not attach the legacy error handler. Execute the complete
local gates in [development](development.md#required-local-checks), then use only
a separately authorized test workbook for shadow acceptance. Compare structure,
coverage, explicit currency and official figures; differences from account sums
are legitimate. Exercise empty holdings, unknown values, a failed write and
manual preservation. Review every child table and terminal count with the
[reference consumer](mcp-consumer.md). Do not treat offline mocks as live evidence.

After release acceptance and explicit cutover authorization, drain old executions
and error handlers again. Keep one production execution at a time
(`N8N_CONCURRENCY_PRODUCTION_LIMIT=1`) and prevent concurrent manual executions;
Google Sheets has no atomic compare-and-set lock. The control row complements
this operational exclusion. Set the candidate control row to its configured
provider/writer/generation and `ACTIVE`, then run manually. Validate success-last
terminal membership, official allocation, coverage, freshness and manual sheets.
Only then may the operator publish its 07:30 `Europe/Paris` schedule. Verify the
first scheduled run independently and again check the 48-hour freshness rule.
Do not activate both providers on one workbook.

A failed write can leave partial physical rows. It cannot publish a valid
observation without a unique successful terminal. In-graph errors may write
fixed `MCP_SYNC_FAILED` telemetry after control/header checks; hard process loss
can leave no terminal at all. Preserve evidence and retry a fresh observation
only after assessing the failed run. A lost successful terminal response never
authorizes overwriting that success with failure.

## Rollback

Pause and drain the MCP writer and manual launches. Preserve the entire 3.0
workbook, its MCP observations and all later manual edits. Reconcile manual
`allocation_targets`, `asset_overrides` and `cashflows` deliberately into a
separate compatible 2.1 workbook. Produce and record the reconciled manual-sheet
digest and run `scripts/migrate-workbook.py rollback-check` with `--source` set
to that 2.1 inventory, `--target` to the preserved paused MCP inventory,
`--reconciled-manual-digest`, and a private `--output`. Review the returned IDs.

Restore only the legacy provider, schema URL, workbook and legacy workflows.
Its first manual successful run and subsequent 07:30 run require independent
verification. Rollback does not delete MCP observations, reverse-map IDs by
appearance or overwrite unresolved mappings. OAuth revocation remains a separate
explicit operator decision.

Source contract 1.1.0 preserves up to 64 fractional digits as exact decimal text
(24 integer digits). This is a bounded project policy, not an upstream maximum.
API and workbook schemas remain 3.0; the frozen legacy 2.1 path is unchanged.
The candidate writer rejects source-contract 1.0.0 snapshots and terminal rows;
never relabel old observations. Regenerate migration plans and use a fresh
isolated candidate when testing a previous 1.0.0 candidate. Existing observations
remain preserved, with incompatible comparisons treated as series breaks.

## Isolated local acceptance stack

Use `docker-compose.mcp-test.yml` as a standalone file, never as an override on
production. The fixed `finary-mcp-candidate` project has its own network and n8n
volume; localhost ports are 8001 (bridge) and 5679 (n8n). Image pins match the
canonical stack. No existing n8n state, private-provider settings, Google tokens
or production environment file is imported. The bridge alone mounts the
operator's isolated OAuth directory. Its bind mount cannot create a missing
source directory. Stop host-side users of that OAuth state before container use.

From the repository root, with `FINARY_MCP_TEST_DIR` still set to the explicitly
bootstrapped test directory, set `FINARY_MCP_CANDIDATE_WORKBOOK_ID` to the reviewed
candidate and generate a separate bridge API key without writing an environment file:

```bash
export FINARY_MCP_CANDIDATE_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
COMPOSE_ENV_FILES=/dev/null docker compose --env-file /dev/null \
  -p finary-mcp-candidate -f docker-compose.mcp-test.yml config --quiet
COMPOSE_ENV_FILES=/dev/null docker compose --env-file /dev/null \
  -p finary-mcp-candidate -f docker-compose.mcp-test.yml up -d --build --wait
```

Keep those exports for later commands; do not print the resolved Compose
configuration or share environment dumps. Open `http://localhost:5679` and create
the independent test owner. n8n generates its own encryption key in its new
private data volume; do not copy a production key or database. Import only the
inactive MCP export and configure an independent Google credential in this test
instance. Register its displayed OAuth callback URL in the operator-owned Google
client. Never export or read Google credentials from another n8n instance.

Starting this empty instance does not authorize portfolio writes. Keep the
candidate writer control PAUSED and the imported workflow inactive until the
operator approves the reviewed manual shadow run. Serial manual execution is
required. Do not publish the schedule during isolated acceptance. Stop only this
project with the same arguments and `stop`; preserve its volume and OAuth state
until the operator has accepted cleanup. Never use the production project name
or `down -v` in this procedure.

## Isolated natural-expiry acceptance

This opt-in test retains one bridge-owned OAuth HTTP session in memory between
two bounded native portfolio collections. It waits until the SDK expiry derived
from the issuer's `expires_in` has naturally elapsed, without changing tokens,
clocks or collection limits. It verifies an expired SDK state, a new persisted
renewal generation, a later advertised expiry and a second valid observation.
The two MCP transport sessions remain separate, as in the production client.
This proves advertised expiry and renewal in the same OAuth session; it does not
probe whether the server would reject a deliberately reused expired token.

Keep the test workbook PAUSED and n8n unpublished. Stop only the isolated bridge
before using its renewable state from the host; do not run bootstrap, revoke or
another collection concurrently. The existing independent test authorization is
sufficient and no browser consent is initiated. From the repository root:

```bash
docker stop finary-mcp-candidate-finary-bridge-1
cd finary-bridge
FINARY_MCP_LIVE_TEST=1 \
FINARY_MCP_LIVE_ISOLATED_STATE=1 \
FINARY_MCP_LIVE_EXPIRY_TEST=1 \
FINARY_MCP_LIVE_STATE_PATH="$FINARY_MCP_TEST_DIR/oauth.json" \
python -m pytest -q -s --tb=no -m live \
  tests/live/test_mcp_live.py::test_isolated_natural_expiry_renewal
```

The default maximum wait is 7,200 seconds; an explicit
`FINARY_MCP_LIVE_EXPIRY_MAX_WAIT_SECONDS` may raise it up to 86,400. Missing expiry,
an already expired initial state or an advertised lifetime beyond that bound
cannot produce successful evidence. A structural countdown is printed at most
every 30 seconds. Leave the process running without sleeping the computer. A
successful result ends with NATURAL_EXPIRY_RENEWAL_VALIDATED. Interruption or
failure is not evidence of successful renewal. No tokens, amounts or identifiers
are printed. Restore the isolated bridge after the test exits if needed:

```bash
docker start finary-mcp-candidate-finary-bridge-1
```

Ordinary CI skips this test. Synthetic wait-bound regressions exercise unknown
expiry, elapsed expiry, excessive lifetime and wall-clock discontinuity without
network calls; they do not establish a live token lifetime.

## Server-side revocation evidence on a dedicated disposable grant

Use a separate newly created `finary-mcp-revocation.*` directory and independent
bootstrap. Never point this test at the candidate bridge, assistant connection
or an ongoing expiry test. The explicit `FINARY_MCP_LIVE_REVOKE_DISPOSABLE=1`
flag authorizes revocation of this dedicated grant. Do not run the ordinary
revoke command first: the test needs the current renewable state in memory to
probe the server after the production revoke command clears local state.

```bash
FINARY_MCP_LIVE_TEST=1 \
FINARY_MCP_LIVE_ISOLATED_STATE=1 \
FINARY_MCP_LIVE_REVOKE_DISPOSABLE=1 \
python -m pytest -q -s --tb=no -m live \
  tests/live/test_mcp_revocation_live.py::test_disposable_server_revocation
```

The directory comes only from `FINARY_MCP_REVOCATION_TEST_DIR`. The test verifies
native initialization/discovery, retains the current grant and access token in
memory, releases the session lease, then invokes the production generation-bound
revoke command. It probes the freshly validated token endpoint using the same
public-client refresh parameters as the pinned SDK. Only HTTP 400 with OAuth
`invalid_grant` establishes remote renewal rejection; local file absence,
network errors, invalid-client errors or HTTP success alone do not qualify.
A separate native discovery probe uses the retained access token without
refresh or consent and reports whether it is still accepted, rejected with
HTTP 401 or inconclusive. No portfolio tools, workbook writes, identifiers,
tokens or raw error bodies are printed or saved by this test.

SERVER_REFRESH_REVOCATION_VALIDATED means remote refresh rejection was observed;
only `immediate_access_revocation: true` also establishes immediate rejection of
the retained access token. A still-accepted access token is an explicit limitation,
not proof of complete access revocation. Failed probes require review and are
not retried automatically with a new consent. The disposable local state remains
cleared by the production revocation path.

Clerk documents grant-scoped revocation for an OAuth application and distinguishes
revocable opaque tokens from JWT access tokens that remain valid until expiry:
[revocation reference](https://clerk.com/docs/reference/backend/oauth-applications/revoke-token)
and [OAuth implementation](https://clerk.com/docs/guides/configure/auth-strategies/oauth/how-clerk-implements-oauth).
Those platform statements guide this test but do not replace observed Finary
behavior. Ordinary CI skips it; synthetic classifiers separately reject
malformed, transient and unrelated authorization failures as evidence.
