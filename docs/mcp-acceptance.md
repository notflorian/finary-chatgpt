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
| #87 | `mcp_client.py`, `mcp_auth.py`, lazy protected injection; SDK 2.2.0 | Native synthetic discovery, errors and OAuth lifecycle in `test_mcp_integration.py` / `test_mcp_auth.py` | Implemented candidate; actual registration, consent, revision, granted scopes, renewal and isolated revocation remain unverified |
| #88 | Adapter resource index, bounded all-account pagination, opaque keys, native valuation, ownership and bank freshness | Production-wire pagination, empty/unsupported, duplicate-looking accounts, shared connections, denomination and identity regressions | Offline implementation; semantic qualifiers retained, nonempty loan mapping unavailable |
| #89 | Typed authoritative `/v3/snapshot`; legacy routes preserved | Real SDK → adapter → service/API; every snapshot fixture checked against production models and exported validator | Offline implementation; live collection still gated by independent authorization |
| #90 | Canonical 3.0 schema, frozen 2.1 path, detached/native copy migration, ledger, exact-pair override and rollback checks | Native fake-HTTP migration/replay/lost-response/manual preservation; writer compatibility and same-day histories | Offline implementation; no Google workbook was migrated; live candidate acceptance pending |
| #91 | Generated inactive MCP workflow, complete prewrite gate, RAW serialization, in-graph fixed failure telemetry and success-last terminal | Exported Code nodes; actual pinned graph/connector, restored execution IDs, response-loss and null/zero/blank transitions | Offline implementation; final required runtime gate recorded below; operational draining still required |
| #92 | Protected independent budget and explicit-label search | Periods/leap dates, returned filters, legitimate zero, unpriced/history contradictions and unknown target currency | Implemented with explicit history/rate/target limitations; no scheduled budget or cashflow writes |
| #93 | Protected complete-response goals with typed plans and explicit account references | Empty/reordered/duplicate-name plans, null fields, currencies, unknown cadence, unresolved references and no progress | Implemented as on-demand plans; no stable goal IDs or inferred progress |
| #94 | Nine-action matrix, versioned source guidance and production reference consumer | Successful membership, mixed-run/provider rejection, duplicate terminals, explicit dated fallback and compatibility tests | Implemented; live reads and retained observations remain separate |
| #95 | Integrated harness, opt-in isolated structural test and executable operator runbook | Required local and CI gates; distinguish engine, connector, fake Google and live evidence | Incomplete acceptance: independent live OAuth and separately authorized shadow workbook still required |


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
negotiated revision and authenticated transport remain unverified.

Public resource metadata identifies `https://public-api.finary.com/mcp` and
issuer `https://clerk.finary.com`, with header bearer authentication and resource
scopes `openid profile email`. Issuer metadata advertises authorization-code and
refresh-token grants, S256, dynamic registration, client metadata documents,
`offline_access`, and token revocation. These are declarations, not successful
registration, granted-scope, token-lifetime or revocation evidence. No private
payload or authentication state was inspected or retained.

## Executed checks

Current branch results are being finalized. Historical PR #96 results are not
current-branch validation. The full required gates will be recorded after the
latest run completes; earlier failed iterations are not reported as passing.

Already executed: all three workflow imports; model/workbook/workflow parity;
JSON and Compose validation; Ruff and mypy (18 production modules); wheel build
and inspection confirming the exact contract and production modules are included.
Targeted synthetic suites cover API/auth, optional capabilities, migration and
the reference consumer. Full native runtime results and final pytest/CI totals
are recorded in the final evidence update.

## Acceptance blockers and operator action

No independent consent, authenticated Finary initialization, real pagination,
renewal, cold restart or revocation was performed. No assistant-managed token
was inspected. No production workflow, volume or workbook was used. Public
metadata and synthetic SDK behavior cannot establish real server acceptance.
Nonempty loan semantics and unverified rate/ownership interpretations remain
qualified in the API rather than being invented.

Next: the operator should authorize a **fresh isolated bridge connection** using
`python -m app.mcp_auth bootstrap --state <new-private-absolute-path>` on a local
machine with a browser, then run the explicit isolated structural probe from
[the runbook](mcp-operations.md). Record only structural outcomes. Real renewal,
cold restart and disposable-connection revocation are separate evidence steps.
A shadow write additionally requires an explicitly authorized test workbook.
The PR remains draft and references the roadmap without claiming parent closure.
No child issue is automatically closed while integrated acceptance is outstanding.
