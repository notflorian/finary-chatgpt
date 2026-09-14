# Architecture

## Purpose

Finary Portfolio Data supports official Finary MCP exclusively.
The [MCP contract](finary-mcp-contract.md)
is the semantic foundation for implemented API 3.0 and workbook 4.0. Its fixture oracle
is test-only; the runtime uses the pinned native SDK, bridge-owned OAuth,
production validators, adapter, service and protected routes. Independent
live acceptance is tracked in [the matrix](mcp-acceptance.md).
The bridge converts unstable upstream responses into
a stable versioned API, then synchronizes validated data into a Google workbook
that ChatGPT can read.

```text
                         local Docker Compose network
                  +-------------------------------------+
                  |                                     |
Finary <----------+ finary-bridge <- HTTP <- n8n        |
                  |                         |            |
                  | schema-server ----------+            |
                  +-------------------------|------------+
                                            v
                                      Google Sheets
                                            |
                                            v
                                    ChatGPT Project
```

The Compose project runs three services:

- `finary-bridge`: FastAPI application and the only Finary-aware component;
- `schema-server`: credential-free internal delivery of the canonical workbook
  schema;
- `n8n`: scheduler, validation layer, Google Sheets synchronization, and
  operational telemetry.

The bridge and n8n bind to localhost. The schema server has no host port.

## Official MCP implementation

`mcp_client.py` owns initialization, capability/schema discovery, pagination of
the catalog, bounded native results and fixed errors. `mcp_auth.py` owns explicit
operator consent and separate renewable state. `mcp_adapter.py` owns resource
relationships, account/holding pagination, currency evidence and ownership.
`mcp_snapshot_service.py` binds the official overview and detail into one UUID
and collection window. `mcp_optional.py` isolates budget/search/goals from the
portfolio critical path. No scheduled call carries an analytics prompt.

The generated inactive MCP workflow validates all rows before portfolio writes,
checks the writer generation, preserves exact decimal text and publishes terminal
membership after required writes. Loan detail remains unavailable. Workbook 4.0 is generated directly from
`current_workbook` in the MCP contract, with no prior layout dependency.
[Operations](operations.md) initializes new workbooks and defines writer activation.

## Trust boundaries

### Finary boundary

The official adapter owns MCP transport, independently authorized OAuth,
resource relationships and sanitized errors. Its fixed `finary_official_mcp`
provenance identifies each observation; it is not a configurable source switch.
There is no private adapter, fallback, mixed snapshot or field supplementation.

### Automation boundary

n8n sees only the normalized bridge contract and the canonical workbook schema.
It does not receive Finary credentials, session cookies, or bearer tokens. The
optional `FINARY_BRIDGE_API_KEY` protects snapshot calls from other local
clients.

n8n owns Google OAuth credentials. Credential bindings are runtime-only and are
not present in exported workflow JSON.

### Consumer boundary

Google Sheets contains normalized portfolio state, user-managed analytical
inputs, and sanitized synchronization telemetry. It does not contain Finary or
n8n credentials, raw API responses, or generic metadata blobs.

In the implemented workbook path, ChatGPT reads the private workbook through a
Project Google Drive source. The
Project receives the workbook semantics as a separate knowledge file, but it
never connects to the bridge or Finary directly.

## HTTP boundary

`main.py` authorizes MCP requests before constructing `NativeMcpClient`.
`mcp_auth.py` then opens protected renewable state and the bounded HTTP transport.
`mcp_adapter.py` validates source relationships and `mcp_snapshot_service.py`
assembles a qualified observation. `errors.py` defines the shared error envelope.
No private-client cache, reset hook, raw model graph or legacy serializer remains.

## API contracts

`GET /health` returns `status: ok`, `service: finary-bridge`, and application
`version: 2.0.0` without constructing a client, reading OAuth state or using
network I/O. OpenAPI is similarly local.

`GET /v3/snapshot` is canonical and returns `McpSnapshotV3`, API schema `3.0`.
`GET /v3/budget`, `GET /v3/spending-search` and `GET /v3/goals` preserve their
independent supported response contracts. They never run as part of snapshot
collection. Removed `/v1/snapshot` and `/v2/snapshot` return 404 with no aliases,
redirects or OpenAPI entries.

A nonempty `FINARY_BRIDGE_API_KEY` requires an exact `X-API-Key` match using
constant-time comparison before client construction. Missing/invalid keys return
401 `BRIDGE_AUTH_FAILED`; an unset/empty configured key leaves local protection
optional. Errors use `{error: {code, message, retryable}}` with fixed sanitized
messages. MCP invalid arguments return 400, unavailable authorization/capability
503, timeouts 504 and other supported MCP failures 502. Request validation and
access logging must not expose search labels or upstream payloads.

## Money and coverage

Official overview totals and allocation have independent authority. Account or
holding details never replace them. Preserve exact decimal text, native currency,
verified EUR provenance, ownership and separate retrieval/valuation/semantic/
freshness coverage. Unknown amounts remain null; no speculative conversion is
performed. See the [focused contract](finary-mcp-contract.md).

## Independent OAuth

The verified official OAuth issuer remains `https://clerk.finary.com`.
Issuer validation and OAuth endpoint allowlisting are mandatory. This legitimate
Clerk hostname does not retain the removed private password, session-cookie,
bearer-renewal or MFA implementation. No assistant/plugin authorization is reused.

Explicit operator consent bootstraps protected renewable state. The MCP store
persists registration metadata, refresh token, effective scope and rotation
generation in a 0700 directory/0600 file. Access tokens remain memory-only.
Atomic writes, CAS generation checks, bounded renewal and process leases prevent
stale replacement and concurrent refresh. Routes and schedules remain
noninteractive. `finary_mcp_data` is bridge-only and separate from `n8n_data`.
The repository no longer mounts or declares the old private session volume;
existing operator volumes must not be read, converted or deleted by cleanup.
See [OAuth operations](mcp-operations.md#backups-and-independent-oauth).

## Synchronization topology

The inactive MCP export supports manual execution and a 07:30 Europe/Paris
schedule. It creates a UUID-bearing n8n run identity, fetches the canonical schema
and `/v3/snapshot`, validates them, reads all required headers and rows, and checks
writer control before preparing and validating every batch. It then upserts
current and observation tables, rechecks writer generation and terminal
collisions, and records success after all required writes.

Only complete collection evidence permits current-row inactivation. Inactive
rows retain their observation identity and timestamps. History is immutable per
accepted observation, including multiple observations on the same date. Empty
batches continue exactly once without dummy rows. Manual inputs are never
synchronization-owned. Exact decimal text is written RAW and null cells clear
explicitly with empty strings.

The same graph handles sanitized failures under its own control/header/terminal
checks. No separate error workflow is required. A lost terminal response cannot
overwrite a stored success. Sequential Sheets reads/writes and control rechecks
are not atomic; operational single-writer exclusion remains necessary.

The production consumer validates actual headers, metadata, terminal membership,
counts, keys, coverage and normalized financial semantics. It can return
independently validated dated history when current tables are inconsistent,
without borrowing later account metadata.

## Versioning

Application 2.0.0 and API 3.0 remain unchanged. Workbook 4.0 removes transitional
columns/tables, so it requires a new layout major. Source contract 2.0.0 reflects
the breaking workbook definition under its coordinated-major policy; it does
not claim a new upstream MCP version or new financial evidence. Old and
transitional workbooks are rejected. No migration or dual-layout reader exists.

## Deliberate limitations

Production acceptance remains an operator gate. Unverified source semantics
retain explicit qualifiers. Debt detail remains unavailable; overview debt
valuation has separate coverage. The system is local and single-user, performs
no speculative FX conversion, and does not execute trades.
