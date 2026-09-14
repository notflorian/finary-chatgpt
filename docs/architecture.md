# Architecture

## Purpose

Finary Portfolio Data supports official Finary MCP exclusively.
The [MCP contract](finary-mcp-contract.md)
is the semantic foundation for implemented API/workbook 3.0. Its fixture oracle
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
membership after required writes. Loan detail remains unavailable. Migration is
append-only against a distinct candidate workbook; the legacy writer explicitly
fetches the frozen 2.1 contract. See [operations](mcp-operations.md) and
[consumer interpretation](mcp-consumer.md). The frozen 2.1 workflow design below
remains for workbook cleanup; it cannot synchronize against the MCP-only bridge.

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

## Retained workbook design

The following frozen legacy-workbook material awaits the workbook and broader
documentation cleanup. It does not describe supported HTTP routes or a runnable
private provider in application 2.0.0.

## Synchronization topology

The daily workflow supports manual execution and a 07:30 `Europe/Paris`
schedule. It:

1. creates a random UUID with the verified n8n execution ID, saves that opaque
   `run_id` in initialization output, and loads
   workbook schema `2.1` from the internal schema server;
2. requests `/v2/snapshot`;
3. validates schema, entities, keys, headers, and safety gates;
4. reads and applies exact-match asset overrides;
5. prepares all rows before any portfolio write;
6. upserts current accounts and positions;
7. updates liability state only for `COMPLETE` coverage;
8. upserts same-day position history with `run_id` membership and the daily summary;
9. writes one terminal `sync_runs` row.

The prewrite gate has two independent boundaries. `Validate Snapshot` uses a
generated projection of the Pydantic field contract, rejects malformed objects,
extra fields and invalid scalar values, and applies only canonical model
defaults before overrides. Metadata scalars are validated and then discarded
under the empty downstream allowlist. Existing key, reference, coverage and
monetary safety checks still apply. This is defense in depth: the canonical
FastAPI response model normally prevents malformed snapshots from reaching n8n.

`Prepare Validated Rows` validates all six write batches against the canonical
workbook columns, order, types, nullability and enum bindings before emitting
the first account row. It also checks keys, run context, counts, observation
membership and shared totals. A malformed history, daily or provisional success
row blocks every portfolio write. Retained current rows selected for inactivation
are explicitly decoded from Sheets encodings and validated without replacing
their previous observation timestamps or run IDs. Missing required retained
values stop the run; this gate does not repair historical data. Finalization
still checks execution identity and timing after the required writes and
validates the final terminal row before its write. The prewrite gate rejects
existing run IDs; both daily terminal paths reread telemetry before writing.
Failure replays require the same identity and original start; collisions leave
existing terminal records intact.

Explicit count checks branch around empty position and history write batches;
liability writes use their existing independent batch check. Each check reduces
the preceding batch to one control item, so the exclusive skip and write paths
continue once. Successful empty table reads use n8n's `alwaysOutputData` and row
preparation discards their empty control items. No dummy row reaches Sheets.
A complete zero-position run updates accounts and the daily summary, inactivates
retained positions without changing observation timestamps or IDs, writes no
history observation, and publishes a zero-count terminal record only after the
required writes. Old history, including earlier same-day runs, is retained.

Current-state rows that disappear become inactive rather than being deleted.
History is append-retained across dates and idempotently replaced for the same
date and position key. Consumers accept history only when its run membership
and count match the terminal successful run and daily row. Physical current
tables also require full-table key/activity validation and active membership and
counts matching the selected successful execution, including account references.
Inactive rows retain their last observation ID even when rewritten; failed
inactivation can invalidate prior active counts. Liability details are validated
independently against the latest successful COMPLETE run. Consumers use only
independently validated historical fallback or aggregates when details fail;
they never combine partial current writes with a successful historical state.
See the [consumer procedure](finary-portfolio-data-knowledge.md). The success marker
is written last; partial Google Sheets writes can invalidate the prior same-day
state, but the mismatch is detectable and a retry repairs deterministic keys.
Manual sheets are never synchronization-owned. Read-side checks reject observed
inconsistencies but cannot make sequential Sheets reads transactional. The
executable consumer specification is test-only and is not deployed in ChatGPT.

Native node retries stay inside the same n8n execution and retain its identity.
A saved-data execution retry receives a new n8n execution ID but can retain
earlier node output, so the workflow checks identity again immediately before
publishing success. A stale saved identity cannot create a successful terminal
marker; recovery then requires a full new execution, except when only the final
terminal Sheets write itself is being retried after all required writes passed.

Structured bridge failures stop before portfolio writes and may record sanitized
failed telemetry. The linked error workflow derives correlation from the
originating failed n8n execution supplied by the Error Trigger and retrieves its
saved initialization through the local n8n API with a runtime-only credential.
It verifies exact source context and never derives correlation from the error
workflow's own execution, retry ancestry or wall-clock time. Missing origin data
stops telemetry with a sanitized diagnostic. Fresh UUIDs prevent database ID
reuse from reusing workbook identity; database replacement requires draining
source executions and error handlers. See the
[adoption and restore procedure](operations.md#adopting-restore-safe-run-identities).
Both workflows use finite
timeouts, and Sheets operations use bounded retries. Read nodes execute once to
prevent quota amplification.

## Versioning

Application `2.0.0`, API `3.0`, workbook `3.0` and source-contract `1.1.0` are
distinct versions. `/v3/snapshot` is the canonical route. The application bump
reflects removal of private support and V1/V2 routes; it does not change MCP
financial semantics. Workbook self-containment and final release documentation
remain separate release requirements.

## Deliberate limitations

Production acceptance remains an operator gate. Unverified source semantics
retain explicit qualifiers. Debt detail remains unavailable; overview debt
valuation has separate coverage. The system is local and single-user, performs
no speculative FX conversion, and does not execute trades.
