# MCP integration acceptance

Integration branch: `codex/issue-85-official-mcp-integration`, based on
`ce5f1e7c82ad686e66cc02c03aab4d8dc61a8aa6`. On 2026-09-11 the working tree was
clean, foundation PR #96 was merged, #86 was closed, #87–95 were open, and no
pull request was open. All issue bodies and comments were inspected.

This matrix tracks implementation and evidence separately. A synthetic test is
not evidence of authenticated Finary behavior. Production activation, workbook
migration, release publication and revoking existing connections are excluded.

| Child | Implementation stage | Required evidence | Status / blockers |
| --- | --- | --- | --- |
| #87 | `mcp_client.py`, `mcp_auth.py`, lazy protected injection; SDK 2.2.0 | Native synthetic discovery, errors and OAuth lifecycle in `test_mcp_integration.py` / `test_mcp_auth.py` | Operator reported successful registration, consent and MCP 2025-11-25 discovery; fresh-process renewable-state recovery succeeded; revocation request accepted and subsequent local collection blocked; granted scopes and natural expiry remain unverified; dedicated live revocation rejected refresh with invalid_grant while the retained access token remained accepted |
| #88 | Adapter resource index, bounded all-account pagination, opaque keys, native valuation, ownership and bank freshness | Production-wire pagination, empty/unsupported, duplicate-looking accounts, shared connections, denomination and identity regressions | Offline implementation; semantic qualifiers retained, nonempty loan mapping unavailable |
| #89 | Typed authoritative `/v3/snapshot`; legacy routes preserved | Real SDK → adapter → service/API; every snapshot fixture checked against production models and exported validator | Offline implementation; first live collection failed response validation, operator-reported source-contract 1.1.0 structural collections passed in separate processes (7.73s and 8.15s) |
| #90 | Canonical 3.0 schema, frozen 2.1 path, detached/native copy migration, ledger, exact-pair override and rollback checks | Native fake-HTTP migration/replay/lost-response/manual and auxiliary-tab preservation; writer compatibility and same-day histories | Operator-authorized native test-candidate migration validated; independent control/ledger readback confirmed; operator reported live migration replay; authorized manual shadow sync and production-consumer readback passed |
| #91 | Generated inactive MCP workflow, complete prewrite gate, RAW serialization, in-graph fixed failure telemetry and success-last terminal | Exported Code nodes; actual pinned graph/connector, restored execution IDs, response-loss and null/zero/blank transitions | Offline runtime gate recorded below; authorized isolated manual run reached success-last and fresh Sheets readback passed; production draining remains an operator action |
| #92 | Protected independent budget and explicit-label search | Periods/leap dates, returned filters, legitimate zero, unpriced/history contradictions and unknown target currency | Implemented with explicit history/rate/target limitations; no scheduled budget or cashflow writes |
| #93 | Protected complete-response goals with typed plans and explicit account references | Empty/reordered/duplicate-name plans, null fields, currencies, unknown cadence, unresolved references and no progress | Implemented as on-demand plans; no stable goal IDs or inferred progress |
| #94 | Nine-action matrix, versioned source guidance and production reference consumer | Successful membership, mixed-run/provider rejection, duplicate terminals, explicit dated fallback and compatibility tests | Implemented; live reads and retained observations remain separate |
| #95 | Integrated harness, opt-in isolated structural test and executable operator runbook | Required local and CI gates; distinguish engine, connector, fake Google and live evidence | Authorized isolated shadow sync and fresh production-consumer readback passed; remaining OAuth lifecycle evidence and production acceptance still required |


Implementation order follows the child dependency graph: client → detail →
snapshot → workbook → workflow; optional reads remain independent of portfolio
collection, followed by consumer interpretation and integrated acceptance.

## Public protocol evidence

The released [SDK package](https://pypi.org/pypi/mcp/2.2.0/json) is `mcp 2.2.0`,
MIT, Python >=3.10. Its dependencies include `mcp-types==2.2.0`, `httpx2`, AnyIO,
Pydantic >=2.12, JSON Schema, PyJWT/cryptography, Starlette and Uvicorn. The bridge
continues to require Python >=3.12. Implementation follows the
[v2 client](https://py.sdk.modelcontextprotocol.io/client/),
[transport](https://py.sdk.modelcontextprotocol.io/client/transports/) and
[OAuth](https://py.sdk.modelcontextprotocol.io/client/oauth-clients/) documentation.

An unauthenticated native SDK probe on 2026-09-11 returned HTTP 401 for POST,
with a challenge identifying the public protected-resource metadata. No consent,
registration or tool call was performed. Initialization did not complete, so the
that probe did not establish a negotiated revision or authenticated transport.
The later operator bootstrap evidence is recorded below.

During the first operator bootstrap attempt, the browser did not open and no
client registration was persisted. A public-only reproduction found that SDK
OAuth metadata requests omitted the HTTP client's default `User-Agent`: the
same metadata endpoint returned HTTP 403 without identification and HTTP 200
with `finary-bridge/1.1.0`. The transport now supplies that header only when
absent. The real SDK subsequently completed public discovery and reached the
registration boundary, where the probe deliberately blocked transmission.
No registration, token exchange or portfolio read occurred in that probe.
The opt-in `bootstrap --diagnose` output now reports fixed stages/status codes,
and the CLI preserves allowlisted failure codes without raw exception text.

Public resource metadata identifies `https://public-api.finary.com/mcp` and
issuer `https://clerk.finary.com`, with header bearer authentication and resource
scopes `openid profile email`. Issuer metadata advertises authorization-code and
refresh-token grants, S256, dynamic registration, client metadata documents,
`offline_access`, and token revocation. These are declarations, not successful
registration, granted-scope, token-lifetime or revocation evidence. No private
payload or authentication state was inspected or retained.

## Executed checks

Executed locally on 2026-09-11 using Python 3.14.5 and the pinned n8n image:

| Check | Result | Evidence boundary |
| --- | --- | --- |
| `python -m pytest -m "not live" --ignore=tests/live -n 4 --dist worksteal` from `finary-bridge` | 3,603 passed, 48 skipped, 161.81s | Current precision revision; skipped Docker cases are executed separately; live tests were excluded |
| Required parallel n8n runtime command, existing three modules plus `test_mcp_runtime.py` | 48 passed, 280.43s | Real pinned n8n 2.35.5 engine and installed Sheets connector, synthetic I/O, network disabled, disposable stores |
| Exact precision revision | 12 passed | Native SDK, optional types, exported JS equality at the last digit and old-contract rejection; full engine/connector preservation is included in the runtime gate |
| SDK/auth/optional bootstrap follow-up | 129 passed | Includes missing HTTP identification and secret-safe bootstrap diagnostics |
| Collection diagnostic observer with native integration tests | 100 passed; final shape-report refinement 5 passed | Test-only observation of unchanged validators; private values and remote schema contents remain hidden |
| Ruff / mypy | Passed; 18 production modules | Local static checks |
| JSON / generated model, workbook and workflow parity | Passed | Canonical contract and generated sources agree |
| Compose configuration | Passed with `COMPOSE_ENV_FILES=/dev/null` | No local secrets loaded |
| Portable workflow import | All three exports passed | Isolated import, separate from graph/connector execution |
| Wheel build and inspection | Passed | Packaged contract exactly matches the reviewed source; production modules included |
| Changed documentation targets, credential-pattern scan and diff whitespace | Passed | Review checks, not a claim of live acceptance |

The full local suite and 48-case runtime gate include the consumer correction
found during integration. Earlier failing iterations are not counted as passing.
The bootstrap fix passed all five jobs in
[CI run 34626554172](https://github.com/notflorian/finary-chatgpt/actions/runs/34626554172).
Collection diagnostics are a subsequent test-only change. Every push also runs
the full Python 3.12 CI suite, Python 3.14 compatibility checks and mandatory
runtime gate. CI status belongs to the latest head of
[PR #97](https://github.com/notflorian/finary-chatgpt/pull/97), not a historical run.

## Acceptance blockers and operator action

On 2026-09-11 the operator supplied structural output showing registration HTTP
201, browser consent/callback, token exchange HTTP 200 and final `AUTHORIZED`
with MCP revision `2025-11-25` and required-tool discovery. This is operator-run
live evidence, not a synthetic result. The subsequent fresh-process collection
failed with `MCP_MALFORMED_RESPONSE`; structural diagnostics identified an account balance exceeding the former
18-digit fractional bound, with no exact reduction by trimming zeros. Source
contract 1.1.0 extends the project bound to 64 fractional digits without rounding.
The operator then reported `STRUCTURAL_COLLECTION_VALIDATED`, protocol
`2025-11-25`, and one passing live test in 7.73s with this revision. The test
executes the production native client, adapter and snapshot service in a new
Python process. A second operator invocation without bootstrap also passed
in 8.15s with the same protocol revision, supporting reuse of renewed state.
Since access tokens are memory-only and restart loads an expired
placeholder with the stored refresh token, this also supports cold-start renewal
through the implemented path. It does not establish natural in-session expiry,
long-term consent validity, concurrent live refresh or server-side revocation.
No assistant-managed token was inspected.
No production workflow, volume or workbook was used.
Nonempty loan semantics and unverified rate/ownership interpretations remain
qualified in the API rather than being invented.

After explicitly authorizing revocation of the disposable connection, the
operator reported `REVOCATION_REQUEST_ACCEPTED`. A subsequent structural test
failed as expected in 0.01s at `SESSION_INITIALIZATION` with
`MCP_AUTH_UNAVAILABLE`. This is expected negative acceptance evidence for local
blocking after state removal, not a passing portfolio-collection test. The
operator has not separately reported browser behavior for this invocation.

Current acceptance status: native migration replay, authorized portfolio shadow
synchronization, fresh consumer readback and real Sheets interruption/recovery
and null transitions have passed. Dedicated live revocation proves server-side
refresh rejection, while the retained access token remains accepted. Natural
in-session expiry/renewal is still awaiting the operator's running test; the
issuer-advertised lifetime observed during setup was approximately 24 hours.
Long-term consent validity, granted-scope review and concurrent live refresh
remain unverified. Production cutover and the first scheduled run have not been
performed and remain separate operator actions.

PR #97 is ready for review, not a draft, as verified on 2026-09-11. It references
the roadmap without claiming parent closure. No child issue is automatically
closed while integrated acceptance remains outstanding. CI results must be
checked on the latest pushed commit, independently of historical results below.

Read-only inspection of an operator-designated test workbook found an auxiliary
chart tab alongside the legacy headers. The native migration now preserves
auxiliary grid tabs, binding their user-owned content into the source inventory
and rejecting changes, missing tabs, extra candidate tabs or reserved-name
collisions. Sixteen synthetic native migration tests pass, including replay,
response loss and retained later edits. The full credential-free suite passed
with 3,615 tests and 48 Docker skips in 92.12s from finary-bridge; the earlier
root-directory invocation failed test collection and is not counted as passing.
Ruff, mypy, JSON/generated parity and diff checks passed. A native candidate
copy was created and its tab metadata verified. The operator then reported
validated native inventory, detached plan/apply/verify and live request preflight.
After explicit approval restricted to the test candidate, native apply returned
VALIDATED. Independent connector readback confirmed 24 tabs, original tab order
including the auxiliary chart tab, one PAUSED 3.0 MCP writer control and one
VALIDATED migration ledger. Portfolio synchronization had not yet run at that
migration stage. Subsequent migration replay and authorized synchronization
passed, as recorded below; no production activation occurred.

The operator reported successful native migration replay, then bootstrapped a
new isolated MCP connection with AUTHORIZED / protocol 2025-11-25 / required
tools. A standalone candidate Compose file now prepares separate ports, network
and n8n storage with no private-provider settings or production environment
file. Synthetic configuration validation passed and is included in CI. The
operator subsequently started all three isolated services, connected the test
Google credential and completed the authorized manual shadow synchronization.

The first isolated n8n partial execution stopped at snapshot validation before
Sheets reads. Both real HTTP requests returned 200, but text-mode full responses
used the installed node's default `data` property while the validator required
`body`. The generator now explicitly selects `outputPropertyName: body` for
both fetch nodes. Earlier graph tests substituted HTTP nodes and did not cover
this transport shape. A new required runtime regression executes both installed
HTTP nodes against a loopback-only synthetic server in a network-disabled
container, then continues through the exported validator and graph. It passes
without changing the production validation rules. The inactive test workflow
was patched in place, preserving all 66 Google credential associations.

After refreshing the patched inactive workflow, the operator reported the
expected Read writer_control row: schema 3.0, official MCP provider, generation
1, the configured test writer and migration, and PAUSED state. That partial
execution established the Sheets control read; the subsequent authorized write
and independent readback are recorded below.

HTTP-boundary follow-up validation: full credential-free suite 3,615 passed and
49 Docker skips (110.50s); mandatory isolated engine/connector gate 49 passed
(220.75s), including actual HTTP nodes. All three portable imports, Ruff, mypy,
Compose, JSON/generated parity, documentation links and diff checks passed.


## Authorized live shadow synchronization and readback (2026-09-11)

After the operator explicitly authorized one manual portfolio synchronization
against the separate migrated test candidate, the installed n8n workflow reached
Record MCP Success with SUCCESS_WITH_WARNINGS. Read-only inspection of the
isolated execution confirmed no node errors and one terminal output after the
required writes. The six allowlisted warnings comprised two STALE_SOURCE, two
BROKEN_CONNECTION, one OWNERSHIP_WORDING_CONFLICT and one UNVERIFIED_DETAIL.
These qualifiers remain visible; success does not establish fresh bank data or
complete debt detail. Manual tables were absent from the prepared write batches.

The operator restored writer_control to PAUSED. An initial partial read reused
cached prewrite inputs and was explicitly rejected as readback evidence. After
clearing execution data and rerunning the read-only chain, all canonical table
headers and cells passed the exported production decoder. The decoded rows were
piped in memory to app.mcp_consumer.select, without saving live payloads or
printing portfolio values. It returned WORKBOOK_READBACK_VALIDATED: PAUSED
control, complete current selection, no dated fallback, operationally non-stale
observation and a series break. The selected terminal matched the authorized
manual run; every expected table membership count passed. Debt detail remained
unavailable rather than zero. No write node executed during this readback.

This is live installed-connector write/read and production-consumer evidence,
not a simulation or an additional synchronization. No schedule was published
and no production workbook was changed. This observation alone did not establish
OAuth expiry, revocation or null transitions; the later dedicated revocation and
Sheets tests below provide their own evidence. Production cutover and the first
scheduled execution remain unperformed. Synthetic failure regressions remain a
separate evidence category.


## Dedicated live server-side revocation evidence (2026-09-11)

The operator authorized a separate disposable connection while the natural-expiry
test continued on its original isolated state. The opt-in revocation test reported
one pass in 4.03s: DISPOSABLE_CONNECTION_VALIDATED, accepted production revocation,
SERVER_REFRESH_PROBE / REJECTED_INVALID_GRANT and SERVER_ACCESS_PROBE /
STILL_ACCEPTED. Its final SERVER_REFRESH_REVOCATION_VALIDATED result explicitly
set immediate_access_revocation to false. This establishes server-side rejection
of the retained refresh grant, rather than merely local state removal. It does
not establish immediate loss of access: the retained access token still completed
native MCP initialization and required-tool discovery. No portfolio tool was
called by that probe. The repeated accepted-revocation line in pytest output
comes from the production command's captured print plus the test's structural
report, not a second invocation of revocation.

Immediate access revocation must not be advertised. The token's eventual rejection
and the separate natural-expiry renewal run remain unverified until their own
results are observed. No production or assistant-managed connection was revoked.


## Real Google Sheets interruption, recovery and clearing (2026-09-11)

The operator authorized a new disposable workbook containing only synthetic
values and canonical headers, with four inactive manual workflows built from
the production export. The first run stopped deliberately after the installed
Sheets node wrote accounts_current. Independent native-cell readback confirmed
one account and no positions, observation or terminal success. Execution evidence
confirmed only the accounts writer ran before the expected stop.

A fresh null-valued run recovered successfully without duplicating the account.
The next run wrote the exact synthetic decimal
123.123456789012345678901234; Google userEnteredValue confirmed string storage
for both native and independently supported EUR current-value cells. A final
run returned both cells to actual blanks. Independent readback found one current
account, one current position, three unique historical positions, three
observations and three distinct successful terminal runs with matching membership.
All canonical tables were reread within bounded ranges and passed the production
consumer: a complete current selection and all three individual observations
validated. The disposable writer control was then returned to PAUSED.

These are live installed-connector writes and native Google cell readbacks with
synthetic source data, separate from authenticated Finary portfolio evidence.
The tested interruption is a deliberate graph stop after a completed write,
not a killed process, an interrupted HTTP request or a lost Google response.
Those other failure cases retain their separately recorded isolated runtime
evidence. No production data or ongoing OAuth expiry state was used.
