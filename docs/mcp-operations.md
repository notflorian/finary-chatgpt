# Independent MCP OAuth and isolated checks

Follow [Operations](operations.md) for the complete fresh-workbook setup, writer
activation, synchronization and readback procedure. Application 2.0.0 uses API
3.0, workbook 4.0 and source contract 2.0.0. These checks require an explicitly
designated isolated environment; they do not activate production.

## Backups and independent OAuth

1. Record deployed versions, workflow revisions, workbook ID,
   headers, row counts and manual edits in a private
   operator record. Do not put portfolio exports in the repository.
2. Back up n8n state and its encryption key separately using the existing
   [backup procedure](operations.md#backup-and-restore). Test restoration in an
   isolated environment. Never use production volumes in test containers.
   Preserve native Google workbook copies so formulas, formats, protections and
   manual notes survive. Do not use `docker compose down -v`.
3. Do not back up renewable Finary state. MCP has its own bridge-only named
   volume; old private state is no longer mounted. The MCP store persists only
   client registration
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

## Isolated local acceptance stack

Initialize a separate fresh workbook with writer ID `mcp-test-writer` and
generation 1 using [Operations](operations.md#fresh-workbook-initialization).
The isolated stack accepts explicit `FINARY_MCP_CANDIDATE_WRITER_ID` and
`FINARY_MCP_CANDIDATE_WRITER_GENERATION`; match them to its control row.

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

Use a newly authorized workbook containing only canonical 4.0 headers and an
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
   blank `current_value_amount` / EUR projection cells.
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
