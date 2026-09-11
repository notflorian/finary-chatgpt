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
| #87 | `mcp_client.py`, `mcp_auth.py`, lazy protected injection; SDK 2.2.0 | Native synthetic discovery, errors and OAuth lifecycle in `test_mcp_integration.py` / `test_mcp_auth.py` | Operator reported successful registration, consent and MCP 2025-11-25 discovery; granted scopes, renewal lifecycle and isolated revocation still need acceptance |
| #88 | Adapter resource index, bounded all-account pagination, opaque keys, native valuation, ownership and bank freshness | Production-wire pagination, empty/unsupported, duplicate-looking accounts, shared connections, denomination and identity regressions | Offline implementation; semantic qualifiers retained, nonempty loan mapping unavailable |
| #89 | Typed authoritative `/v3/snapshot`; legacy routes preserved | Real SDK → adapter → service/API; every snapshot fixture checked against production models and exported validator | Offline implementation; first live collection failed response validation, account balance precision identified; source-contract 1.1.0 live retry pending |
| #90 | Canonical 3.0 schema, frozen 2.1 path, detached/native copy migration, ledger, exact-pair override and rollback checks | Native fake-HTTP migration/replay/lost-response/manual preservation; writer compatibility and same-day histories | Offline implementation; no Google workbook was migrated; live candidate acceptance pending |
| #91 | Generated inactive MCP workflow, complete prewrite gate, RAW serialization, in-graph fixed failure telemetry and success-last terminal | Exported Code nodes; actual pinned graph/connector, restored execution IDs, response-loss and null/zero/blank transitions | Offline implementation; final required runtime gate recorded below; operational draining still required |
| #92 | Protected independent budget and explicit-label search | Periods/leap dates, returned filters, legitimate zero, unpriced/history contradictions and unknown target currency | Implemented with explicit history/rate/target limitations; no scheduled budget or cashflow writes |
| #93 | Protected complete-response goals with typed plans and explicit account references | Empty/reordered/duplicate-name plans, null fields, currencies, unknown cadence, unresolved references and no progress | Implemented as on-demand plans; no stable goal IDs or inferred progress |
| #94 | Nine-action matrix, versioned source guidance and production reference consumer | Successful membership, mixed-run/provider rejection, duplicate terminals, explicit dated fallback and compatibility tests | Implemented; live reads and retained observations remain separate |
| #95 | Integrated harness, opt-in isolated structural test and executable operator runbook | Required local and CI gates; distinguish engine, connector, fake Google and live evidence | Incomplete acceptance: remaining OAuth lifecycle and separately authorized shadow workbook still required |


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
A successful operator collection under this revision remains unverified.
Successful portfolio collection, renewal/cold-restart acceptance, expiry and
isolated revocation remain outstanding. No assistant-managed token was inspected.
No production workflow, volume or workbook was used.
Nonempty loan semantics and unverified rate/ownership interpretations remain
qualified in the API rather than being invented.

Next: the operator should rerun the isolated structural probe with
`FINARY_MCP_LIVE_DIAGNOSTICS=1` and `--tb=no`, using the existing disposable
bridge state described in [the runbook](mcp-operations.md). Report only the
structural diagnostic, never portfolio values or OAuth state. Real renewal,
cold restart and disposable-connection revocation are separate evidence steps.
A shadow write additionally requires an explicitly authorized test workbook.
The PR remains draft and references the roadmap without claiming parent closure.
No child issue is automatically closed while integrated acceptance is outstanding.
