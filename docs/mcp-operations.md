# Independent MCP candidate acceptance and cutover

This runbook is executable preparation for an operator. It does not authorize
production activation. Independent consent, cold-start renewal, server-side refresh
revocation, authorized shadow synchronization and real Sheets recovery/clearing
have live evidence. Natural-expiry renewal in one OAuth session also passed.
Production acceptance remains a separate operator action.
The retained access token remained accepted after revocation; do not promise
immediate access invalidation. See the dated
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

## Production target register and approval stages

This is the bounded production plan for #95. The
[release decision matrix](mcp-acceptance.md#release-decision-and-production-evidence)
records the recommendation and the still-pending operator decisions. Existing
test-workbook permissions do not authorize any production stage below. Complete
repository preparation and publish its draft PR before requesting production
authorization. Keep `Refs #95` until actual cutover and scheduled acceptance are
supported; merge, tag and release publication follow their own authorization.

On 2026-09-13 no production target register or HANDOFF.md was supplied in this
checkout. Do not derive designations from `.env` defaults, accessible connectors,
worksheet names, or historical test IDs. Resolve the following in an
operator-controlled private record outside Git before requesting stage A:

| Private record entry | Required reviewed value / current preparation |
| --- | --- |
| Code | Full proposed deployment SHA, review and five matching CI job URLs; actual deployed SHA stays unset until deployment. Pin the preparation commit in the PR; later evidence-only commits are separate |
| Host and deployment | Designated host, checkout/artifact, Compose project and exact files, n8n instance URL/identity, local ports, volumes and current image IDs; current live configuration is UNVERIFIED |
| Current binding | Confirm actual provider, bridge route, schema URL, workbook and legacy/error workflow revisions; expected legacy path is `private_api`, `/v2/snapshot`, API 2.0, frozen workbook 2.1 |
| Intended binding | `finary_official_mcp`, `/v3/snapshot`, API/workbook 3.0, source contract 1.1.0, canonical schema URL and reviewed inactive MCP export |
| Workbook targets | Exact original legacy ID; exact IDs for existing targets, or approved folder/name/access for new native backup and MCP copies. Record newly created IDs in stage A before authorizing B. Designate a separate rollback 2.1 copy; never overwrite/relabel the sole original |
| Writer | Unique designated `FINARY_MCP_WRITER_ID`, migration ID and initial generation **1** (the helper creates it; there is no generation CLI flag). Confirm `FINARY_MCP_WRITER_GENERATION=1` and one matching singleton control |
| Execution exclusion | All schedules, published versions, error-handler links/deliveries, running/waiting/queued/retrying executions, other writer integrations and manual launch paths; designated person holding the maintenance window |
| Google access | Approved credential selected inside the designated n8n instance for every Sheets node; independently operator-supplied in-memory Google access for native migration/readback, never extracted from n8n/plugin |
| Independent OAuth | Bridge-owned grant/state path, local filesystem/host, process owner and sole mount; existing status is only local presence, not live validity. New consent/transfer/recovery needs explicit scope in the authorization |
| Backups and manual state | Separate private n8n archive and encryption-key locations, restore workspace, native workbook copies, inventories/plans and reconciliation record; manual/auxiliary editors agree on the freeze |
| Release decision | Named operator, offset timestamp, accepted limitations, core/optional dispositions, approved stages/targets, maintenance window, stop conditions and rollback scope |

Version pins come from the reviewed files, not contract-number arithmetic:

| Component | Repository value | Deployment verification |
| --- | --- | --- |
| Bridge service | `1.1.0` in `pyproject.toml` and service metadata | Record Git SHA and built image ID; no new tag/version is implied |
| Bridge runtime | Dockerfile `python:3.12-slim`; `mcp==2.2.0` | Base tag and other dependency ranges are not immutable. Record resolved base/image digest, Python version and installed package versions privately at build time |
| n8n | `2.35.5`, digest `sha256:c5861e6016c8f283142584190e3874e6aa6f322eca8771ceead09d08b4766a1e` | Match designated runtime to `docker-compose.yml` |
| Schema server | `nginx:1.31.4`, digest `sha256:db35bfc6b2951e7f8a72db5db120288c127ffaeeb4a6d4b95a26fead017d5913` | Serve both reviewed JSON artifacts with their exact bindings |
| Validation runtimes | CI Python 3.12.14 / compatibility 3.14.6 and Node 22.23.2 | Require the candidate's own CI; these are not claims about the running host |

The service version `1.1.0`, source contract `1.1.0`, API/workbook `3.0` and
retained workbook `2.1` are independent version domains. Compare deployed schema,
workflow and packaged contract bytes to the exact approved checkout. Do not
deploy moving `main`, a newly merged SHA, or an unreviewed helper correction
under approval for a different revision. Repository workflows remain inactive
and contain no runtime credential IDs.

Approval can cover multiple stages and their conditional steps together. Within
that scope, continue without another question for each node or command. A
material target/revision change, failed guard or action outside scope stops the
stage; elapsed time is never authorization.

1. **Stage A — final production preparation.** After explicit authorization for
   the registered targets, pause legacy schedules and relevant error delivery;
   drain all execution/retry paths and exclude manual launches. Freeze human
   edits, establish consistent backups and native copies, verify recoverability,
   regenerate the final inventory/plan/requests and review them. No portfolio
   synchronization or migration batch is included in stage A. Its native-copy
   writes and service stopping must be named in the approval.
2. **Stage B — migration and manual cutover.** Requires review/authorization of
   the final plan and requests, exact deployment revision, targets and recovery
   scope. Recheck exclusion and source/destination state; apply only the reviewed
   native migration, validate preservation/ledger/PAUSED control, deploy matching
   bridge/schema/workflow bindings and approved credentials, then authorize the
   control and execute one full new manual production run. Expected writes are
   appended migration cells/tables in the separate destination, configured
   control, normalized current/history/child tables and sanitized terminal
   telemetry. Manual sheets and auxiliary content remain user-owned.
3. **Stage C — schedule acceptance.** May be approved with B, conditional on
   manual acceptance. Publish only the reviewed MCP schedule at 07:30
   `Europe/Paris`, retaining serial execution and manual exclusion. Independently
   validate its first actual trigger as below. If not yet due, record PENDING
   and resume this PR after it occurs; do not change the schedule, rename a
   manual run or create an automation.
4. **Recovery scope.** Approve pausing/draining and evidence preservation on a
   failed guard. A fallback may use only the reviewed reconciled 2.1 destination
   and complete legacy bindings described under [rollback](#rollback). If those
   targets or manual reconciliation are not ready, remain paused. New OAuth
   bootstrap or revocation is never implied by rollback.

## Consistent backup and migration baseline

A preliminary read while writers are active is planning evidence only. Native
`inventory` and detached `plan` can help prepare the review, but never pass
`--writers-drained` for a live source that has not been drained. Both native
`requests` and `apply`, and detached `apply`, require that assertion. The flag
does not inspect n8n or prevent humans from editing Sheets.

After stage A draining, verify no running, waiting, queued, saved retry or
delayed error delivery can resume. Keep schedules unpublished across restarts;
record the last validated legacy run and its business date. Stop the designated
stack cleanly before archiving its database. Follow
[backup and restore](operations.md#backup-and-restore), with these cutover checks:

- Archive only the designated `n8n_data`, never either `finary_session_data`
  **or** `finary_mcp_data`; do not archive all Compose volumes or the project
  directory wholesale. Keep the matching encryption key in a separate secure
  location. If n8n generated a key in its settings file, ensure the recovery
  archive excludes that key material and the separate secure copy is usable;
  do not alter the live settings file or print its contents.
- Record archive checksums privately, verify the archive can be read and restore
  it to a fresh disposable volume with no Finary mounts. Check SQLite integrity
  on the restored database. In a network-isolated unpublished recovery instance,
  verify workflow/execution metadata and practical credential decryption with
  the separately supplied key without displaying/exporting credential values.
  Do not start restored schedules or replay saved executions into Google. Record
  fixed pass/fail outcomes; a checksum alone is not a restore test.
- Keep the original legacy workbook untouched. Create separate native backup
  and destination copies; verify original tab order, headers/keys, complete
  history, manual rows, auxiliary grid tabs, formulas, notes, formats, charts,
  protections and sharing restrictions. JSON/CSV alone is not a native backup.
  Preserve the complete native grid alongside typed inventories in a private
  directory (0700; files 0600), outside the repository.
- Reread source and destination after the freeze and use the final source for
  the commands below. Verify both native copies against that baseline. Renew
  the plan if rows/manual content changed since preliminary review; obtain
  review of changed requests before B. Digests do not prove absence of a writer.
  Stop on unsupported layout, duplicate keys, inconsistent canonical state,
  auxiliary/reserved-name conflicts, oversized requests or unresolved edits.
  Reconcile explicitly; do not weaken the helper or invent a crosswalk.

Names, tickers, ISINs and row order cannot verify identifiers. Unresolved mappings
and legacy overrides stay unapplied. The existing `verified_override` function
requires an enabled override, exact legacy/MCP pair, `VERIFIED` state, dated
review and evidence reference. No automatic override transfer is in this plan.
Migration JSON is private Google workbook data; never commit it or raw upstream
Finary payloads. No backup/recovery step uses `docker compose down -v`.

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
   token authentication method), a renewable refresh token, SDK-effective scope
   and a rotation generation. That scope can be explicitly returned or inferred
   by the SDK; format 1 does not retain its provenance. No bearer access token,
   authorization code, PKCE secret or callback state is persisted.
   Directory/file permissions are 0700/0600;
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
   issuer's consent page. Its constructor preference is `openid profile email
   offline_access`; the SDK selects the effective request from the challenge
   and metadata, so this string is not proof of the sent or granted scopes.
   It uses authorization code + S256 and public-client dynamic registration.
   Independent registration/consent/discovery succeeded in the dated operator
   evidence; this does not guarantee a future grant. If unsupported, it returns
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
   of the MCP revision header. That probe checks public discovery only; later
   registration, consent and collection have separate dated evidence.
5. Status reports local restart-state presence and `live_validity: UNVERIFIED`;
   it is not a connectivity, granted-scope or consent assertion. It performs no
   HTTP, refresh, consent, revocation or state replacement. For a separately
   authorized connection requiring new cold-start evidence, use the structural
   collection below. Existing cold-start and natural-expiry evidence is already
   recorded; do not repeat those tests without a concrete new need.
   Never print amounts, IDs or token bodies:

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

## Authorization operating constraints

The [scope evidence table and lifecycle dispositions](mcp-acceptance.md#authorization-scope-disposition-2026-09-13)
are the engineering handoff to #95, not production approval. Keep `mcp==2.2.0`
and the existing constructor preferences/SDK selection. The supported setup is
the independently consented public client with protected renewable state that
passed core collection and renewal. It is not a certified minimum-scope set.
Identity scope names do not establish portfolio permissions. Do not trim scopes
by name or infer missing scopes from an old state file. Budget, spending-search,
goals and identity access have separate acceptance; the scheduled core uses
only overview, accounts and holdings.

Run one bridge owner of one OAuth state on a local filesystem, on one host.
Do not share it with host probes, extra workers, replicated containers or another
host. Tasks using one SDK provider share its AnyIO lock; separate sessions use
the process lease, held for the entire OAuth HTTP session. A competing process
waits approximately 10 seconds then may fail with `MCP_AUTH_UNAVAILABLE` before
any HTTP. Short storage-lock contention can fail immediately. This is an
accepted bounded failure, not evidence that consent has been revoked. Wait for
the owner to finish and retry a fresh collection; do not loop bootstrap to cure
contention. Independent-process regressions use synthetic HTTP and do not
certify concurrent behavior at the live issuer. Network filesystems and manual
state/lock-file edits or removal are unsupported.

For replacement or recovery, drain users of this state first. The CAS generation
prevents an old in-flight refresh from overwriting a newer operator replacement,
but it cannot invalidate an already cached access token. Use a fresh process to
adopt a replacement immediately. All state writers must obey this protocol;
keep directory/file modes 0700/0600 and transfer only through the private
operator procedure. A crash after issuer rotation but before local persistence
can require explicit recovery; local atomic writes cannot make the remote
exchange transactional.

Consent remains subject to issuer policy and operator actions. One natural
expiry/renewal success does not prove indefinite consent or server rejection
of a deliberately reused expired token. Unavailable/revoked authorization and
insufficient scope cause bounded, sanitized failure; scheduled routes never
open a browser, register another client or fall back to the private provider.
The failed run may record telemetry but cannot overwrite portfolio state. Use
the last validated successful observation with its date; after 48 hours it is
operationally stale, even if a later failure row is newer.

On persistent authorization failure, inspect local `status` on the designated
bridge state and check for an overlapping owner before deciding recovery. If
renewable authorization is unusable, keep scheduled collection paused and
obtain explicit authorization for operator bootstrap/replacement. Do not print
or share state contents. Validate the recovered connection through an authorized
fresh-process structural collection, then restore scheduling only under the
applicable operational approval. Transient transport failures do not justify
new consent or revocation.

Revocation request acceptance, local state removal, refresh rejection, access
expiry and remote access rejection remain distinct. The disposable live grant
rejected refresh with `invalid_grant` but still accepted its retained access
token for discovery. Eventual rejection of that token is unverified. Stop local
users when retiring a connection; local stopping/removal cannot guarantee remote
invalidation of another retained copy. General Clerk documentation below is
context, not Finary-specific evidence. No new revocation or expiry wait is
required by the engineering disposition.

#95 owns acceptance of these limitations against the intended deployment commit
and CI, production-specific migration/cutover authorization, the first scheduled
run and rollback readiness. If release policy requires exact historical scopes,
least privilege, live concurrency or stronger revocation guarantees, those are
new evidence requirements. A new test cannot recover the historical grant's
provenance; prospective evidence needs a separately designated and authorized test.
Do not reuse assistant/plugin-managed grants or repeat completed shadow tests
to infer independent bridge permissions.

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
   final command, using a separate `--output "$MIGRATION_DIR/applied.json"` so
   the reviewed requests remain intact. Immediately beforehand, reread the
   original source into a separate file and compare it with the final source
   and native backup; the helper checks the destination but does not reread the
   live source for you. Any change stops application. Rerun `requests` into
   `revalidated-requests.json` and require
   `cmp -s "$MIGRATION_DIR/requests.json" "$MIGRATION_DIR/revalidated-requests.json"`
   to succeed before proceeding. The apply interface reconstructs requests from
   the plan/current destination; it does not accept the reviewed requests file.
   Maintain exclusion throughout this check and application. Then run:

   ```bash
   python scripts/migrate-google-workbook.py apply \
     --source "$MIGRATION_DIR/source.json" \
     --native-backup "$MIGRATION_DIR/source.native.json" \
     --plan "$MIGRATION_DIR/plan.json" --writers-drained \
     --output "$MIGRATION_DIR/applied.json"
   ```

   This sends one bounded Google batch. A lost response triggers
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
   typed rows and validated ledger on initial application. Before retrying an
   uncertain result, inspect the ledger/current native state. The ledger replay
   path does not repeat every native cell/format comparison: independently
   revalidate preservation and later edits; never blindly resend `addSheet` or
   column requests. No MCP observations are deleted on reruns.
   Same-day daily and holding-history rows include observation UUIDs; historical
   provenance absent in 2.1 remains blank/unknown in `legacy_observations`.

## Isolated acceptance, cutover and scheduling

Import the inactive candidate workflow and bind only its operator-approved
Google credential. Do not attach the legacy error handler. Execute the complete
local gates in [development](development.md#required-local-checks), then use only
a separately authorized test workbook if a new shadow evidence need arises.
Existing shadow, recovery and exact-value/null acceptance is already recorded;
do not repeat it to satisfy production acceptance. Compare structure, coverage,
explicit currency and official figures; differences from account sums are
legitimate. Never inject synthetic holdings, null transitions or deliberate write
failures into production. Review every child table and terminal count with the
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

## Fresh production run acceptance

Keep the MCP workflow unpublished until the manual run passes. Bind every Sheets
read/write/failure node to the approved Google credential inside the designated
n8n instance; keep its legacy error workflow unattached. Verify the actual
`FINARY_MCP_SCHEMA_URL`, workbook, writer/generation and bridge provider, plus
`N8N_CONCURRENCY_PRODUCTION_LIMIT=1`. Exclude overlapping manual launches and
all other users of the OAuth state, including host probes. Set `writer_control`
ACTIVE only for this exact migrated destination/writer/generation. Its singleton
row supplements operational exclusion; Google Sheets supplies no atomic CAS lock.

For each accepted manual or scheduled run:

1. Inspect the fresh **full execution**, not a green node or cached partial
   inputs. Privately record workflow revision, actual execution/run/observation
   IDs, start/completion timestamps with offsets and Paris business date. Check
   terminal finalization happened after all required write branches and that
   there is exactly one valid successful terminal for that observation/run.
2. After writes settle, keep competing writers and human edits excluded. Reread
   every canonical table with full headers and complete physical membership,
   including inactive/foreign rows and all terminals; never prefilter or
   deduplicate. Verify native exact decimal strings, actual blank cells and
   genuine zero. Reject truncated ranges and changed/inconsistent reads.
3. Call the actual reference consumer for the **expected run**, then select the
   newest accepted state. A dated fallback or an older success is useful for
   recovery, but cannot accept this new run. The example below reads native
   Sheets directly twice in memory and invokes production functions; there is
   no `python -m app.mcp_consumer` CLI. The native migration CLI's `inventory`
   command assumes 2.1; use its `native_inventory(..., "3.0")` Python interface
   for MCP reads. Do not invent a `--schema-version` flag.

From the repository root with the development virtualenv active, set
`CUTOVER_EXPECTATION_FILE` to a private JSON record populated from the registered
target and actual n8n execution. It contains `workbook_id`, `run_id`,
`observation_id`, `writer_id`, integer `writer_generation`, `migration_id`,
`control_state` (`ACTIVE` or deliberately `PAUSED`) and `snapshot_date`.
It contains no credentials. Run only within the approved readback scope:

```bash
python - <<'PY'
import getpass
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.mcp_consumer import observation, require, select

spec = importlib.util.spec_from_file_location("native", "scripts/migrate-google-workbook.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
try:
    expected = json.loads(Path(os.environ["CUTOVER_EXPECTATION_FILE"]).read_text())
    client = native.GoogleCandidate(getpass.getpass("Independent Google access token: "))
    try:
        first = native.native_inventory(client.read(expected["workbook_id"]), "3.0")
        second = native.native_inventory(client.read(expected["workbook_id"]), "3.0")
    finally:
        client.http.close()
    require(first == second)
    book = {name: sheet["rows"] for name, sheet in second["sheets"].items()}
    require(type(expected["writer_generation"]) is int and expected["writer_generation"] > 0)
    require(expected["control_state"] in {"ACTIVE", "PAUSED"})
    require(len(book["writer_control"]) == 1)
    require(type(book["writer_control"][0]["generation"]) in {int, float})
    require(book["writer_control"] == [{
        "row_key": "singleton", "workbook_schema": "3.0",
        "provider": "finary_official_mcp", "generation": expected["writer_generation"],
        "writer_id": expected["writer_id"], "migration_id": expected["migration_id"],
        "state": expected["control_state"],
    }])
    terminals = [r for r in book["sync_runs"] if r["run_id"] == expected["run_id"]]
    require(len(terminals) == 1)
    terminal = terminals[0]
    require(type(terminal["writer_generation"]) in {int, float})
    for field in ("observation_id", "writer_id", "writer_generation"):
        require(terminal[field] == expected[field])
    now = datetime.now(timezone.utc)
    result = observation(book, terminal, now=now)
    latest = select(book, now=now)
    require(result["current_complete"] and not result["dated_fallback"] and not result["stale"])
    require(latest["context"]["run_id"] == expected["run_id"] and not latest["dated_fallback"])
    require(result["context"]["snapshot_date"] == expected["snapshot_date"])
    print(json.dumps({
        "status": "WORKBOOK_READBACK_VALIDATED", "current_complete": True,
        "series_break": latest["series_break"], "operationally_stale": result["stale"],
        "warning_codes": sorted({r["code"] for r in result["detail"]["source_warnings"] or []}),
    }))
except Exception:
    raise SystemExit("WORKBOOK_READBACK_REVIEW_REQUIRED") from None
PY
```

This checks exact run identity, versions, unique membership/counts and production
semantics using fresh native cells, with fixed structural output. It neither
proves n8n write ordering nor compares backups, certifies trigger origin or makes
sequential reads atomic. Inspect those separate evidence boundaries explicitly:

- Compare legacy history, manual/auxiliary content and native formats against
  the final baseline; account for any approved human edits. Inactive rows keep
  their last actual observation identity. Preserve every later MCP observation.
- Official overview totals/allocation remain authoritative, even when detail
  sums differ. Unknown loan detail does not become zero debt or authorize loan
  inactivation. Verify no liability rows were written/inactivated. Preserve null
  membership counts as unavailable, and zero as verified empty membership.
- Confirm a provider/view/currency-incompatible baseline produces a series
  break. Retain ownership/rate/detail warnings; `SUCCESS_WITH_WARNINGS` can pass
  with explicit operator acceptance. Never suppress warnings to obtain SUCCESS.
  Record operational freshness and bank-source freshness independently.

Only after manual acceptance and stage C approval publish the existing 07:30
`Europe/Paris` schedule. For the first real scheduled execution, require n8n's
actual trigger/execution metadata and executed Schedule Trigger node, not the
workflow title. Resolve the actual timestamp/offset and Paris business date;
repeat all the checks above with that execution's own expected identity. Confirm
legacy schedules, delayed error handlers and competing manual paths remained
excluded throughout. Do not infer scheduled acceptance from manual output.

On failure, preserve private execution/native evidence and pause/drain further
writes under the approved recovery scope. A partial observation or absent
terminal is unaccepted. Inspect a possibly committed successful terminal before
retrying; never replace it with FAILED on response loss. A full new observation
may recover only after the cause and scope are reviewed. Record pending scheduled
evidence without adding an unrequested automation. Publish only sanitized
outcomes in the same draft PR, tied to the actual deployed code SHA and separate
later documentation revision.

## Rollback

Pause and drain the MCP writer and manual launches. Preserve the entire 3.0
workbook, its MCP observations and all later manual edits. Reconcile manual
`allocation_targets`, `asset_overrides` and `cashflows` deliberately into a
separate compatible 2.1 workbook. Produce and record the reconciled manual-sheet
digest and run `scripts/migrate-workbook.py rollback-check` with `--source` set
to that 2.1 inventory, `--target` to the preserved paused MCP inventory,
`--reconciled-manual-digest`, and a private `--output`. Review the returned IDs.

Record explicit reconciliation decisions for later manual edits and auxiliary
content; MCP-only overrides stay unresolved unless their reverse mapping has
independent exact-pair evidence. Never automatically reverse-convert MCP
observations. Verify the preserved control is exactly one PAUSED row; the helper
does not prove operational draining or completeness of the human reconciliation.
Its source must be the separate reconciled 2.1 copy, never the sole original:

```bash
python scripts/migrate-workbook.py inventory \
  --source "$MIGRATION_DIR/reconciled-legacy.json" \
  --output "$MIGRATION_DIR/reconciled-inventory.json"
python scripts/migrate-workbook.py rollback-check \
  --source "$MIGRATION_DIR/reconciled-legacy.json" \
  --target "$MIGRATION_DIR/preserved-mcp.json" \
  --reconciled-manual-digest "$RECONCILED_MANUAL_DIGEST" \
  --output "$MIGRATION_DIR/rollback-validation.json"
```

Set the digest from the reviewed `manual_digest` in `reconciled-inventory.json`.
Obtain `preserved-mcp.json` from the existing native Python reader above using
`native_inventory(..., "3.0")` and `native.migration.private_write`, together
with a separate full native copy/backup; do not use the 2.1-only inventory CLI
on a migrated workbook. Keep all these artifacts outside Git.

Restore only the legacy provider, schema URL, workbook and legacy workflows.
Its first manual successful run and subsequent 07:30 run require independent
verification. Rollback does not delete MCP observations, reverse-map IDs by
appearance or overwrite unresolved mappings. OAuth revocation remains a separate
explicit operator decision.

Rollback criteria include a mismatched revision/binding, failed migration or
preservation guard, overlapping writer, unavailable authorization preventing
approved recovery, or failed manual/scheduled membership or semantic acceptance.
Pause first and preserve evidence; execute rollback only within approved targets
and reconciliation scope. Restore `FINARY_PROVIDER=private_api`, `/v2/snapshot`,
`FINARY_GOOGLE_SHEET_ID` for the reconciled copy and
`FINARY_SCHEMA_URL=http://schema-server/google-sheets-schema-v2.json` together.
Restore both reviewed inactive legacy workflows and their Google/local n8n API
bindings, then their error-workflow relationship. Keep MCP unpublished/PAUSED.
Use [legacy first-run checks](operations.md#first-run-verification) and independent
scheduled verification before accepting recovery. Existing legacy authorization
is not guaranteed usable; if new consent is needed, remain paused until its
separate authorization and successful recovery.

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

The operator-run test passed on 2026-09-13 in 86,406.46 seconds; the following
procedure is retained for a future concrete evidence need and requires current
authorization for its designated isolated connection. Historical authorization
does not authorize another execution.

Keep the test workbook PAUSED and n8n unpublished. Stop only the isolated bridge
before using its renewable state from the host; do not run bootstrap, revoke or
another collection concurrently. No browser consent is initiated.
From the repository root:

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

## Disposable live Sheets interruption and null transitions

Use a newly authorized workbook containing only canonical 3.0 headers and an
ACTIVE writer_control for `synthetic-live-writer`, generation 1. Do not reuse a
portfolio candidate or production workbook. The developer-only builder requires
the development test dependencies and synthetic native-wire fixtures:

```bash
python scripts/build-mcp-live-scenarios.py --workbook-id "$DISPOSABLE_SHEET_ID" \
  --output /private/tmp/mcp-live-scenarios.json
```

It builds four inactive workflows with no schedule and no Finary HTTP nodes.
Synthetic upstream data passes through the production native client and snapshot
service during generation; only the schema/snapshot fetch nodes are substituted.
All Sheets nodes and downstream validation code remain the production export.
Bind the isolated n8n Google credential locally; never commit a bound export.
Run one stage at a time and independently reread Sheets between stages:

1. `MCP Live Test - interrupt`: expected Stop After First Real Write error after
   the real accounts write. Confirm one account, no position and no success
   terminal; the reference consumer must reject the incomplete workbook.
2. `MCP Live Test - null`: full fresh execution resumes using deterministic
   account keys and a new observation. Confirm a unique complete terminal and
   blank `mcp_current_value_amount` / EUR projection cells.
3. `MCP Live Test - known`: writes the synthetic decimal
   `123.123456789012345678901234`. Read native userEnteredValue to prove exact
   text storage, not a rounded number, then validate complete membership.
4. `MCP Live Test - clear`: verify both native amount cells are blank again,
   one current position remains, and all three successful observations and their
   history survive without duplicate current keys or terminal membership.

Clear cached execution data before any partial readback. Do not rerun a completed
stage blindly: each generated stage contains one synthetic observation UUID;
regenerate for another independent acceptance series. After acceptance, return
the disposable control to PAUSED. The interruption is an intentional graph stop,
not a killed n8n process or simulated Google outage; report that distinction.
A passing offline builder test is not evidence that these live stages ran.
