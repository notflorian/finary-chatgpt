# MCP integration acceptance

Integration branch: `codex/issue-85-official-mcp-integration`, based on
`ce5f1e7c82ad686e66cc02c03aab4d8dc61a8aa6`. On 2026-09-11 the working tree was
clean, foundation PR #96 was merged, #86 was closed, #87–95 were open, and no
pull request was open. All issue bodies and comments were inspected.

This matrix tracks implementation and evidence separately. A synthetic test is
not evidence of authenticated Finary behavior. Production activation, workbook
migration, release publication and revoking existing connections are excluded.

Release-preparation baseline, rechecked 2026-09-13: PR #97 merged at
`0a3ddf57448d71fbadc4ff28c9d5dc8e321c6db2`; PR #98 subsequently merged at
`6b2db62d63197144fcfee1f0014551055ca40a00`. The latter tree is exactly
`2ef74272e5a81d7e04bd4892b57fc503e19893ae`, also the tree of reviewed PR #98
head `0123e54a76da36ee386ef658183031837cca431a`. Issues #86–94 are closed;
#85 and #95 remain open. No PR was open and the local tree was clean before
updating main and creating `codex/issue-95-mcp-release-acceptance`. No nested
AGENTS.md or HANDOFF.md was found. Current issue bodies/comments and both merged
PRs were inspected; the older unchecked #87 items in #85/#95 do not override
#87's closure through the documented-limitation path.

[PR #98 CI 34755653036](https://github.com/notflorian/finary-chatgpt/actions/runs/34755653036)
passed all five jobs on `0123e54a76da36ee386ef658183031837cca431a`: 3,698
credential-free tests, 49 runtime skips in that invocation, and a separate
49-test pinned-n8n/Sheets gate. The separate
[main push run 34756639770](https://github.com/notflorian/finary-chatgpt/actions/runs/34756639770)
is **cancelled**, not green: tests/static/contracts passed, Python 3.14 was
cancelled, and n8n reported 48 passed / 1 failed. The failing
`test_native_terminal_response_loss_preserves_finalized_identity[True]` could
not decode complete CLI execution evidence. That result establishes neither a
production failure nor successful terminal recovery. It must remain visible
alongside new candidate checks. The earlier
[main run 34751985693](https://github.com/notflorian/finary-chatgpt/actions/runs/34751985693)
passed on the PR #97 merge. None of these historical checks is CI for a later
deployment or documentation commit.

## Release decision and production evidence

**Technical recommendation:** proceed to a reviewed, core-portfolio-only cutover
once the target register, exact revision CI, backup/recovery checks and bounded
operator authorization below are satisfied. **Actual operator release decision:
PENDING.** No production target, mutation, manual acceptance or scheduled-run
acceptance is established by this preparation. No existing live experiment was
repeated. This is preparation for #95, not its completion.

Evidence sources used by the decision matrix:

- **E97:** [retained integration evidence at the PR #97 merge](https://github.com/notflorian/finary-chatgpt/blob/0a3ddf57448d71fbadc4ff28c9d5dc8e321c6db2/docs/mcp-acceptance.md).
  The dated entries distinguish operator reports from offline tests; the merge
  records them and does not claim that every earlier experiment ran at that SHA.
- **E98:** [scope/lifecycle disposition at the PR #98 reviewed head](https://github.com/notflorian/finary-chatgpt/blob/0123e54a76da36ee386ef658183031837cca431a/docs/mcp-acceptance.md)
  and [its regressions](https://github.com/notflorian/finary-chatgpt/blob/0123e54a76da36ee386ef658183031837cca431a/finary-bridge/tests/test_mcp_auth.py).
- **C98:** exact PR #98 and main CI results above, kept separate from the
  preparation PR's checks and any eventual deployed revision.

| Decision | Evidence / exact source | Known limitation | Operational consequence | Technical recommendation | Operator decision |
| --- | --- | --- | --- | --- | --- |
| Independent core authorization | E97: independent consent, native discovery, fresh-process renewal; E98 scope trace | Historical exact grant and certified minimum privileges unknown; advertised, requested, explicitly returned and SDK-inferred scopes differ | Preserve supported SDK selection; no least-privilege claim or inferred permission from scope names | Accept documented limitation; #87 is technically resolved | PENDING |
| Renewable local operation | E97: natural expiry/renewal in the same OAuth HTTP session after 86,406.46s; E98: real process leases/CAS with synthetic HTTP | Live multi-process issuer concurrency, multi-host sharing and indefinite consent not certified; bounded contention can fail | One owner, one host/local filesystem; serialize access, monitor freshness and explicitly recover unavailable consent | Accept single-owner topology and interruption/recovery duty | PENDING |
| Connection retirement | E97: disposable refresh rejected with `invalid_grant`; retained access still allowed native discovery | Immediate or eventual remote rejection of that retained access token not established | Stop local users; state removal, refresh revocation and access expiry are separate; revocation needs its own decision | Accept residual-access limitation | PENDING |
| Core semantics and source quality | E97: native collection, manual shadow sync and fresh `app.mcp_consumer.select` readback | Nonempty loans unavailable; ownership/rate semantics qualified; stale/broken bank connections persisted after technical success | Keep official overview/allocation authoritative; no zero-debt inference, loan inactivation or guessed semantics; disclose bank freshness separately from the 48h operational threshold | Accept core with retained warnings, including legitimate `SUCCESS_WITH_WARNINGS` | PENDING |
| Migration and recovery | E97: native test-copy migration/replay/preservation, real synthetic Sheets interruption/recovery and exact text/null transitions; C98: offline contract/runtime coverage | Test targets do not certify production contents; Sheets has no atomic writer CAS; interruption test was a graph stop | Final inventory after drain, separate native copies, one writer/generation, exact-pair crosswalks only; preserve later edits on rollback | Apply reviewed native plan only after target-specific checks | PENDING |
| Release and production execution | C98; [bounded production plan](mcp-operations.md#production-target-register-and-approval-stages) | No designated production targets or accepted production executions recorded | Require exact candidate CI/review, target register, backup proof, manual run, then actual 07:30 Paris run | Keep draft with `Refs #95`; no automatic merge/tag/release | PENDING |

| Capability | Implemented evidence | Proposed release scope | Actual readiness / operator disposition |
| --- | --- | --- | --- |
| Core portfolio | E97 independent bridge/shadow/consumer evidence; E98 authorization disposition and C98 | Include, subject to the decision matrix and production gates | Production acceptance PENDING |
| Budget | Offline period, zero/unpriced/history/target-currency regressions in PR #97; earlier assistant-connector observations are a different grant | Defer independent live acceptance; preserve semantic limitations | Independent bridge live acceptance UNVERIFIED; deferral awaits operator decision |
| Spending-search | Offline explicit-label, returned-filter and zero-value regressions in PR #97 | Defer; any live check requires an explicit user-provided label and authorization | Live acceptance UNVERIFIED; no label supplied or searched |
| Goals | Offline complete-response/null/currency/reference regressions in PR #97; earlier assistant-connector observations are a different grant | Defer independent live acceptance; no inferred identity or progress | Independent bridge live acceptance UNVERIFIED; deferral awaits operator decision |

Optional readiness does not block core unless the operator deliberately includes
that capability. No optional invocation is required to fill this table.

| Production acceptance item | Current outcome | Evidence still required |
| --- | --- | --- |
| Deployment revision and CI | No deployment; candidate will be pinned in the preparation PR | Full reviewed SHA and its five CI jobs; actual image IDs/digests and installed versions |
| Private target register | PENDING; repository defaults and historical test targets are not designations | Host/Compose/n8n, original/destination/backup workbooks, writer, Google binding and independent OAuth ownership |
| Final backup and migration | NOT PERFORMED | Authorized drain, verified restore, final native inventory/plan, ledger and preservation readback |
| Manual production run | NOT PERFORMED | Actual execution/run/observation identity, write ordering and fresh full-table reference-consumer validation |
| First scheduled production run | NOT PERFORMED | Genuine Schedule Trigger, actual offset timestamp/Paris date, independent full readback and no competing writer/error delivery |
| Rollback | Procedure prepared; recoverability UNVERIFIED for production | Preserved MCP workbook and later edits, reconciled separate 2.1 copy, rollback-check and restored manual/scheduled acceptance if used |
| Final release decision | PENDING | Operator acceptance of limitations, scoped outcomes and optional dispositions |

Store workbook identifiers, inventories, digests tied to private contents,
execution details, migration requests and backups only in operator-controlled
storage outside Git. Public updates record fixed outcomes and code/CI references.
Record the actual deployed SHA separately from later documentation-only evidence
commits. If the real scheduled run has not happened, leave it pending and resume
this PR later; do not replace it with another manual run or create an automation.

### Preparation validation (2026-09-13)

Initial preparation at `613dbc765a505ef136406582d08c65d51838af5d` changed only
this record and `mcp-operations.md`. No runtime, schema, portfolio workflow,
OAuth, migration-engine or consumer behavior was changed.
The native helper's existing interfaces suffice; its 2.1-only inventory CLI,
3.0 Python reader, request regeneration and replay-check boundaries are now
explicit in the runbook. No live source or authentication store was inspected.

| Newly executed command / check | Result | Boundary |
| --- | --- | --- |
| `python -m pytest -m "not live" --ignore=tests/live` from `finary-bridge` | **3,747 passed**, no skips, 738.14s | Credential-free; Docker was available, so this includes the 49 runtime cases |
| Exact required four-module `FINARY_REQUIRE_N8N_RUNTIME=1 python -m pytest -q -n auto --maxprocesses 4 --dist worksteal --max-worker-restart 0 --durations=15 ...` command in `docs/development.md` | **49 passed**, 194.80s | Separate pinned-n8n 2.35.5/Sheets gate, synthetic I/O, network-disabled disposable resources, no production volumes |
| `ruff check app tests`; `mypy app` | Passed; 18 source files checked by mypy | Local static analysis |
| `python scripts/validate-json.py`; `python scripts/build-workflow-validation.py --check` | Passed | Canonical JSON, packaged contract and generated workflow parity |
| `COMPOSE_ENV_FILES=/dev/null docker compose config --quiet`; `COMPOSE_ENV_FILES=/dev/null bash scripts/validate-n8n-imports.sh` | Passed; all three inactive imports | No production environment or volumes loaded |
| Both migration CLIs' `--help`; documented readback example exercised against synthetic native HTTP | Interfaces inspected; five scenarios passed | Valid run accepted; wrong run, changing reads and boolean control/terminal generations rejected; no Google request |
| Documentation targets/anchors, new shell/Python example syntax, added-line credential patterns, final diff and `git diff --check` | Passed | Public evidence contains no private workbook identifiers, payloads or credentials |

Local runtimes: Python 3.14.5, MCP 2.2.0, Node 22.12.0 and Docker 29.7.2.
The normal suite and separate runtime gate both passed the historical main-run
failure case without changing its assertions or harness. Its earlier missing
execution evidence is not erased; its cause was not established at this stage.
The later capture regression below supplies separate evidence.
The preparation PR's exact pushed SHA/CI must be recorded separately; local
passes do not certify CI's Python 3.12/3.14 or supported Node 22.23.2 runtimes,
operator approval, production migration or an actual schedule trigger.

The first [preparation PR #99 CI run 34758199024](https://github.com/notflorian/finary-chatgpt/actions/runs/34758199024)
on `613dbc765a505ef136406582d08c65d51838af5d` exposed a concrete CI orchestration
gap: the Python 3.14 compatibility job exceeded its five-minute job limit while
the expanded MCP suite was still progressing (144 of 182 cases reported, no
assertion failure reported before cancellation). GitHub's job annotation confirms
the timeout; the same annotation explains the historical main job cancellation.
Neither cancelled job is a compatibility pass.

The focused correction increases only that CI job's finite timeout from five to
ten minutes and updates `test_ci.py` to retain the timeout check and explicitly
require all four MCP compatibility modules. Test commands, runtime limits,
production write gates and application code are unchanged. The eight CI-boundary
regressions, Ruff and mypy passed after this correction. The full local results
above precede it and are not presented as rerun. The final candidate SHA and its
own CI are pinned in the [PR #99 description](https://github.com/notflorian/finary-chatgpt/pull/99);
the initial preparation SHA is superseded as the deployment proposal. There is
still no deployment or operator approval.

### CLI execution-evidence capture correction

The [next candidate CI run 34758542390](https://github.com/notflorian/finary-chatgpt/actions/runs/34758542390)
on `af2b52298c0e730c4876d2b834be9d0f4759d10f` passed Python 3.14 but again
reported 48 passed / 1 failed in the separate n8n gate. The same terminal-loss
case received incomplete raw CLI JSON. This is a test-evidence transport failure;
an absent decodable result cannot certify the workflow's success or recovery.

Inspection of the installed pinned n8n CLI found JSON logging followed by an
explicit `process.exit`. A new synthetic regression runs the real CLI with a
16 MiB result and a delayed stdout reader to reproduce pipe backpressure. Both
the successful and deliberately failed execution lost decodable JSON before the
fix (two failures in 25.99s); both passed after it (28.23s). Volume alone passed
locally and was not treated as a reproduction. The regression also checks the
complete payload and actual terminal success/error, not merely process exit.

The shared `_execute` test helper now directs CLI output to a temporary file
inside its disposable network-disabled container, then drains that file with
`cat` while retaining the CLI status. It still rejects missing/incomplete JSON;
no assertion, production graph, write/retry/terminal behavior, process timeout or
cleanup rule is relaxed. No project volume or live data is involved. The two
new cases belong to the existing required runtime module, extending that gate
from 49 to 51 cases. The unchanged terminal-loss regression remains required.
The complete required local runtime command passed **51 cases in 217.27s**.
The final success/error-terminal assertion refinement passed both focused cases
again in 30.21s. Ruff, mypy, JSON/generated parity, synthetic Compose configuration,
all three inactive imports, documentation links and diff checks passed again.
The serial full suite was also launched again; its completed result and final
exact-commit CI are recorded in the
[same preparation PR](https://github.com/notflorian/finary-chatgpt/pull/99);
neither earlier candidate is a deployment or final acceptance claim.

## Delivered implementation matrix

| Child | Implementation stage | Required evidence | Status / blockers |
| --- | --- | --- | --- |
| #87 | `mcp_client.py`, `mcp_auth.py`, lazy protected injection; SDK 2.2.0 | Native synthetic discovery, errors and OAuth lifecycle in `test_mcp_integration.py` / `test_mcp_auth.py` | Technical acceptance with documented limits: scope provenance/minimum privileges remain unknown; independent-process synthetic regressions support bounded local contention; retained live renewal/revocation evidence and operating constraints are detailed below |
| #88 | Adapter resource index, bounded all-account pagination, opaque keys, native valuation, ownership and bank freshness | Production-wire pagination, empty/unsupported, duplicate-looking accounts, shared connections, denomination and identity regressions | Offline implementation; semantic qualifiers retained, nonempty loan mapping unavailable |
| #89 | Typed authoritative `/v3/snapshot`; legacy routes preserved | Real SDK → adapter → service/API; every snapshot fixture checked against production models and exported validator | Offline implementation; first live collection failed response validation, operator-reported source-contract 1.1.0 structural collections passed in separate processes (7.73s and 8.15s) |
| #90 | Canonical 3.0 schema, frozen 2.1 path, detached/native copy migration, ledger, exact-pair override and rollback checks | Native fake-HTTP migration/replay/lost-response/manual and auxiliary-tab preservation; writer compatibility and same-day histories | Operator-authorized native test-candidate migration validated; independent control/ledger readback confirmed; operator reported live migration replay; authorized manual shadow sync and production-consumer readback passed |
| #91 | Generated inactive MCP workflow, complete prewrite gate, RAW serialization, in-graph fixed failure telemetry and success-last terminal | Exported Code nodes; actual pinned graph/connector, restored execution IDs, response-loss and null/zero/blank transitions | Offline runtime gate recorded below; authorized isolated manual run reached success-last and fresh Sheets readback passed; production draining remains an operator action |
| #92 | Protected independent budget and explicit-label search | Periods/leap dates, returned filters, legitimate zero, unpriced/history contradictions and unknown target currency | Implemented with explicit history/rate/target limitations; no scheduled budget or cashflow writes |
| #93 | Protected complete-response goals with typed plans and explicit account references | Empty/reordered/duplicate-name plans, null fields, currencies, unknown cadence, unresolved references and no progress | Implemented as on-demand plans; no stable goal IDs or inferred progress |
| #94 | Nine-action matrix, versioned source guidance and production reference consumer | Successful membership, mixed-run/provider rejection, duplicate terminals, explicit dated fallback and compatibility tests | Implemented; live reads and retained observations remain separate |
| #95 | Integrated harness, opt-in isolated structural test and executable operator runbook | Required local and CI gates; distinguish engine, connector, fake Google and live evidence | Authorized isolated shadow sync and fresh production-consumer readback passed; review the authorization limitations below against the intended release commit; production acceptance and cutover remain operator decisions |


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
Collection diagnostics are a subsequent test-only change. Pull-request and main
CI run the full Python 3.12 suite, Python 3.14 compatibility checks and mandatory
runtime gate. PR #97 subsequently merged; current acceptance must use the latest
follow-up commit's CI, separately from these historical results.

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

Acceptance status before this follow-up: native migration replay, authorized portfolio shadow
synchronization, fresh consumer readback and real Sheets interruption/recovery
and null transitions have passed. Dedicated live revocation proves server-side
refresh rejection, while the retained access token remains accepted. On 2026-09-13
the operator reported successful natural expiry and renewal in the same OAuth
session after the approximately 24-hour issuer-advertised lifetime.
Long-term consent validity, granted-scope review and concurrent live refresh
remain unverified. Production cutover and the first scheduled run have not been
performed and remain separate operator actions.

On 2026-09-11 PR #97 was ready for review and referenced the roadmap without
claiming parent closure. Its later merge and child-issue status are recorded
above. CI must be checked on the latest pushed commit, independently of the
historical results below.

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

Immediate access revocation must not be advertised. The revoked access token's
eventual rejection remains unverified. The separate natural-expiry renewal test
subsequently passed, as recorded below; it does not prove revocation of that other
access token. No production or assistant-managed connection was revoked.


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

## Exact numeric-cell decoding regression

Native MCP amount columns are STRING columns and retain the full contract
precision. Review also identified a separate physical-read coercion risk in
NUMBER columns: arbitrary numeric strings could round before validation,
including a fractional writer generation that rounded to an authorized integer.
The decoder now checks exact integer syntax and safe bounds with BigInt before
conversion. Safe integer spellings with trailing fractional zeros remain
compatible; fractional or unsafe values stay strings for later type validation
rather than being silently rounded. Legacy provider exports are unchanged.
Fifteen regressions cover safe boundaries, unsafe integers, 64-place amounts and
the full prewrite rejection of a near-integer writer generation. Eight failed
against the original decoder before the fix. Native text precision assertions
already passed before this correction and remain separate from the NUMBER-cell
coercion defect.

Executed validation for this decoder correction: 65 focused tests passed;
full credential-free suite 3,653 passed with 49 Docker skips (195.59s), followed
by the separately executed mandatory pinned-engine/connector gate with all
49 passed (216.72s). Ruff, mypy, JSON validation, generated parity, Compose,
three inactive workflow imports, local documentation links and diff checks
passed. No live OAuth or Google acceptance run was repeated for this correction.

## Historical fallback and OAuth format review corrections

Historical holdings now reuse standalone production position semantics even
when current account rows belong to another observation. Native/EUR monetary
consistency and holding/account/position key relationships cannot be bypassed
by selecting a dated fallback. No current account metadata is borrowed. Four
corruption regressions reproduced the former acceptance of inconsistent history.
OAuth restart files now require format to be exactly an integer with value 1;
JSON true and 1.0 are rejected. Six format regressions also verify unchanged
file bytes, inode, modification time and permissions after rejection.

Executed checks: 45 focused consumer/auth tests passed; full offline suite
3,663 passed with 49 Docker skips (178.82s), followed by the separate mandatory
engine/connector gate with all 49 passed (202.68s). Ruff, mypy, JSON/generated
parity, Compose, three inactive imports and diff checks passed. These fixes did
not read or modify live OAuth state or rerun live acceptance.


## Natural expiry and same-session renewal (operator report, 2026-09-13)

The isolated natural-expiry test passed in 86,406.46 seconds. Its initial
configuration reported an available expiry, 86,397 seconds remaining and an
86,400-second wait bound. The operator then supplied NATURAL_EXPIRY_OBSERVED
and NATURAL_EXPIRY_RENEWAL_VALIDATED with same_oauth_session true, followed by
one passing live test. The production OAuth HTTP session remained in memory
between two separately bounded native collections. The test did not alter the
clock, token lifetime or stored expiry to force a refresh. Its assertions verify
the expired SDK state, a new renewal generation, later expiry and a new valid
portfolio observation without another consent flow.

This establishes renewal after the issuer-advertised natural expiry in one OAuth
session. It is operator-run evidence, not a locally rerun test or proof that a
revoked access token was rejected. Long-term consent behavior, granted-scope
review, concurrent live refresh and production cutover remain separate limits.
The prior implementation head c1911a1 had all five CI checks green when inspected
on 2026-09-13; subsequent documentation-head CI must be evaluated separately.

## Authorization scope disposition (2026-09-13)

The installed package is exactly `mcp==2.2.0`, matching
[`pyproject.toml`](../finary-bridge/pyproject.toml). Inspection followed
`mcp.client.auth.oauth2.OAuthClientProvider` and
`mcp.client.auth.utils.get_client_metadata_scopes` through the production
[`authorized_http` / `RenewableStorage`](../finary-bridge/app/mcp_auth.py) path.
The current [Python OAuth guide](https://py.sdk.modelcontextprotocol.io/client/oauth-clients/)
was checked for context; its discussion of newer protocol revisions does not
replace the pinned implementation or the observed `2025-11-25` negotiation.
The [negotiated MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization#scope-selection-strategy)
prioritizes challenge scopes, then protected-resource declarations.

| Evidence layer | Result | Source and boundary |
| --- | --- | --- |
| Protected-resource advertisement | `openid profile email` | Public metadata recorded 2026-09-11 and rechecked 2026-09-13 at the [resource metadata endpoint](https://public-api.finary.com/.well-known/oauth-protected-resource/mcp); declaration only |
| Authorization-server advertisement | Allowlisted subset: `openid profile email offline_access`; other advertised names present but withheld | New unauthenticated 2026-09-13 read of [issuer metadata](https://clerk.finary.com/.well-known/oauth-authorization-server); exact case-sensitive membership, fixed four-name output allowlist, no raw response retained |
| Constructor preferences | `openid profile email offline_access` | Production `OAuthClientMetadata`; a preference, not a wire observation or grant receipt |
| Initial SDK authorization request | Challenge scope replaces the preference; otherwise resource scopes, otherwise issuer scopes, otherwise omission. SDK adds exact `offline_access` when advertised and refresh grants are enabled | Installed selector and new synthetic authorization-URL assertions through the actual SDK. With the recorded resource scopes and no overriding challenge, the inferred request is `openid profile email offline_access`. The historical bridge request itself was not retained |
| Explicit issuer token-response scope | Unknown for the historical independent grant | Historical structural reports did not distinguish presence of the raw token-response `scope`. Neither the constructor nor persisted scope proves an explicit issuer return |
| Effective scope with omission | Initial response omission inherits the effective request; refresh response omission carries prior scope forward | SDK `_handle_token_response` / `_handle_refresh_response`, exercised synthetically; standards-based inference, not a new live receipt. Refresh requests omit `scope` |
| Previously stored scope | SDK-effective value, with unrecoverable explicit-versus-inferred provenance; its actual historical value is not present in the sanitized record | `RenewableStorage.set_tokens()` persists `tokens.scope` in format 1. A null prior scope remains unknown on an omitted refresh response; a later explicit response supplies a current value but cannot reconstruct history. No live state file was inspected |
| Independent-grant capabilities exercised | Native initialization/catalog discovery, `get_portfolio_overview`, `accounts`, `holdings`, cold-start renewal and natural-expiry renewal | Previously recorded operator-run structural collections and shadow acceptance above. Successful calls establish usability for those observations, not necessity of each scope or validity today |

The public recheck made only two unauthenticated metadata GETs through the
bounded transport. The initial sandbox attempt failed and is not evidence;
the permitted network retry succeeded. No token exchange, consent, refresh,
revocation, identity or portfolio request occurred. Unexpected advertised names
were represented only by a boolean, never echoed. This is new public evidence,
not newly obtained authenticated acceptance evidence.

[RFC 6749 §3.3](https://www.rfc-editor.org/rfc/rfc6749.html#section-3.3)
defines space-separated, case-sensitive scope tokens. A changed grant must be
reported explicitly; an omitted authorization-request scope instead leaves the
issuer's documented default or rejection policy in control, not a bridge default.
[§5.1](https://www.rfc-editor.org/rfc/rfc6749.html#section-5.1) permits response
omission when the grant matches the request. For
[§6](https://www.rfc-editor.org/rfc/rfc6749.html#section-6), an omitted refresh
request scope refers to the original grant, and successful responses follow
§5.1. The pinned SDK's carry-forward behavior is therefore retained. No
missing-scope error, case folding, substring comparison or invented default is
introduced. Without the original request/response evidence, these rules cannot
recover the historical exact grant.

For a `403 insufficient_scope` challenge the SDK can union previous requested,
stored and newly challenged scopes for step-up authorization. In unattended
bridge mode the default redirect handler rejects that flow before consent or
another authorization-code exchange. The new regression exercises this actual
SDK path. Constructor preferences are not a hard scope ceiling; changed metadata
or a future explicitly authorized bootstrap must be reviewed on its own evidence.

**Technical disposition: supported configuration, minimum privileges unknown.**
Retain the existing constructor preferences, SDK selection, independent public
client registration/consent and protected renewable state. Usable refresh
material is required by the bridge for unattended restart/renewal; the SDK's
conditional `offline_access` request supports that intent. Evidence does not
establish that this name alone guarantees renewal or is strictly necessary at
Finary, nor which identity scopes gate any portfolio permission. Do not remove
scopes based on names. A successful request with a set does not prove every
member necessary or that a smaller set works.

Core collection requires the three exercised portfolio tools and renewable
authorization. Optional budget, spending-search and goals remain separate
on-demand acceptance entries; `get_me` and `profiles` are not core prerequisites.
Their earlier assistant-connector observations in the source contract cannot
establish permissions of this independent bridge grant. No identity scope is
mapped to an assumed portfolio permission. The practical consequence is that
the supported configuration has no certified least-privilege claim. If #95
requires that claim, obtain issuer capability-to-scope guidance and separately
authorize an isolated reduced-scope experiment; a fresh receipt alone would
establish that request, not necessity. No new diagnostic persistence or live
probe is needed to adopt this explicit limitation.

## Lifecycle decisions and release handoff (2026-09-13)

| Question | Existing / newly executed evidence | Unverified point | Supported constraint and technical disposition | Decision retained by #95 |
| --- | --- | --- | --- | --- |
| Can independent processes safely renew the same local state? | Existing in-process task test; new spawned-interpreter tests use `NativeMcpClient`, `authorized_http`, real leases/storage/CAS and synthetic HTTP. A competing process times out before HTTP while the owner retains a session; after release a fresh process renews the latest rotation. Paused successful and rejected refreshes preserve newer operator replacements; failure releases the lease | Live issuer concurrency, crashes during remote rotation before persistence, multiple hosts/replicas/network filesystems | Accept bounded local contention safety, not guaranteed success of every caller. One supported owner and local filesystem; drain for replacement, then start a fresh process. No live concurrency experiment required under this restriction | Accept single-owner topology and possible failed overlapping collections; no replication approval implied |
| Does consent remain usable indefinitely? | Operator-run 86,406.46s natural-expiry test and fresh-process renewal; synthetic expired, missing and `invalid_grant` cases plus insufficient-scope challenges fail with fixed errors without browser consent or registration | Future issuer/operator changes, eventual consent expiry and direct reuse of a deliberately expired access token | Accept renewable, interruptible authorization. Bounded failures stop collection; operator recovery is explicit. No arbitrary multi-day soak or indefinite validity promise | Accept interruption/recovery responsibilities and freshness monitoring |
| Does revocation immediately stop access? | Operator-run disposable-grant refresh rejection (`invalid_grant`) and retained-access discovery success; local removal is separate | Eventual server rejection of that separately revoked access token | Accept refresh revocation with residual-access uncertainty. Stop local users when retiring/replacing a connection; never advertise immediate remote invalidation | Accept residual-access limitation or require separately authorized additional issuer-specific evidence |

The lease starts **before** reading renewable state or fetching metadata and
lasts through the entire `authorized_http` context, including native discovery
and calls. POSIX nonblocking `flock` on the stable `.lease` file is attempted
200 times with 50ms sleeps: approximately 10 seconds of contention waiting,
subject to scheduling. Storage `.lock` operations fail fast on contention and
cover short read/CAS/atomic persistence sections, not HTTP. Generations prevent
an in-flight old refresh from publishing over an operator replacement. The
SDK context's AnyIO lock coordinates tasks sharing one provider; separate
sessions/processes rely on the filesystem lease. The earlier `asyncio.gather`
test alone did not prove process behavior. New process tests retain the real
wait bound and clean up their spawned children; only synthetic HTTP is replaced.

`authorized_http` bounds HTTP at 30 seconds; the native session's collection
deadline is 180 seconds with 30-second call bounds. Unattended mode requires
stored registration and renewable material, excludes registration requests
from the HTTP allowlist and denies redirect/callback handling. Missing/revoked
authorization and insufficient scope cannot launch browser consent or switch
providers. A failed snapshot stops the workflow before portfolio writes;
sanitized failure telemetry may be written. Prior successful state remains
dated and becomes operationally stale after 48 hours. Recovery is described in
the [operator constraints](mcp-operations.md#authorization-operating-constraints).

Engineering conclusion: the remaining authorization items are addressed using
the documented-limitation option in #87. No production defect was established;
production OAuth code, dependency pin, persistence format and API/workbook/source
contracts remain unchanged. #95 must decide release acceptance against the
intended deployment commit and CI, explicitly acknowledge the scope, consent
and revocation limits, assess optional capabilities separately, and own any
authorized production migration, activation, first scheduled run and rollback.
This conclusion is not operator release approval. No authenticated live test,
consent, expiry wait, revocation or shadow synchronization was repeated here.

## Authorization follow-up validation (2026-09-13)

| Check | Newly executed result | Boundary |
| --- | --- | --- |
| Targeted `test_mcp_auth.py` and `test_mcp_integration.py` | 151 passed | Pinned native SDK and production storage/authentication; synthetic HTTP only |
| Full `python -m pytest -m "not live" --ignore=tests/live` from `finary-bridge` | 3,698 passed, 49 Docker cases skipped in the sandbox | Includes 35 added scope/status/process cases; the skipped cases passed separately below |
| Required four-module pinned-n8n runtime command from `docs/development.md` | 49 passed in 191.09s | Real n8n 2.35.5 engine and Sheets connector, synthetic I/O, network-disabled disposable resources; no production volumes |
| Three inactive workflow imports | Passed | Isolated pinned-n8n import command with `COMPOSE_ENV_FILES=/dev/null` |
| Ruff, strict mypy, JSON, generated workflow parity, Compose configuration, diff whitespace | Passed | No application, SDK, OAuth format, schema or workflow changes |
| Changed documentation targets/anchors and credential-pattern review | Passed | Only synthetic OAuth fixtures and fixed public evidence are added |

Local tools were Python 3.14.5, installed MCP 2.2.0 and Node 22.12.0. The
repository-supported Node 22.23.2 and Python 3.12/3.14 compatibility must also be
verified by the follow-up PR's CI on its latest pushed commit; the successful
main baseline above is historical evidence, not that follow-up result.
