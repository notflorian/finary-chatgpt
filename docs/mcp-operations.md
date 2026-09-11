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
   copies, extra tabs, unsupported layouts or oversized plans fail closed.
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
