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
| #87 | Pinned SDK, discovery, bounded transport, independent OAuth, protected routes | Native synthetic transport and OAuth lifecycle; operator consent/restart/renewal/revocation | In progress; no isolated consent supplied |
| #88 | Adapter relationships, pagination, exact native amounts, ownership/freshness | Multi-page/empty/invalid/unsupported fixtures through adapter | Pending |
| #89 | Typed authoritative v3 service and API | Production path, contract parity, legacy route regressions | Pending |
| #90 | Canonical versioned workbook, migration and writer exclusion | Preservation, dry-run/rerun/conflict/rollback tests | Pending |
| #91 | Generated v3 workflow and prewrite gates | Exported code, pinned engine and actual Sheets connector | Pending |
| #92 | Independent budget/search endpoints | Period, currency, counts, quality and argument tests | Pending |
| #93 | Complete goals observation endpoint | Plan variants, reference limits and absence of inferred progress | Pending |
| #94 | Consumer and nine-action source matrix | Successful membership, compatibility and dated fallback tests | Pending |
| #95 | End-to-end harness and operator runbook | Required local gates, latest-head CI, isolated live acceptance | Pending; no test workbook authorized |

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

Implementation results will be recorded here after execution. Historical PR #96
results are not current-branch validation.
