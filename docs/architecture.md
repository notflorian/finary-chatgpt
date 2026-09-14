# Architecture

## Components and trust boundaries

```text
Official Finary MCP ← bridge ← n8n → private Google Sheets → ChatGPT
                                ↑
                         schema-server
```

The local Compose network contains three services. Only the bridge and n8n bind
host ports, both on localhost. `schema-server` serves the canonical workbook JSON
internally without credentials.

The bridge is the only Finary-aware component. `mcp_client.py` owns native SDK
negotiation, discovery and bounded tool calls. `mcp_auth.py` owns independent
operator OAuth and protected renewable state. `mcp_adapter.py` validates resource
relationships, pagination, opaque identifiers, currency and ownership.
`services/mcp_snapshot_service.py` assembles one observation with a UUID and a
collection window. `mcp_optional.py` handles budget, spending search and goals
independently; they are not prerequisites for portfolio collection.

n8n receives normalized observations, never Finary credentials, raw payloads or
OAuth tokens. It owns Google OAuth and writes to one private workbook. Runtime
credential bindings are absent from the repository export. ChatGPT reads the
workbook through its own Google connection; neither the bridge URL nor OAuth
state is a ChatGPT source. Direct Finary MCP questions use a separate connection
and cannot be combined with older workbook detail as one observation.

## HTTP and authorization

The application reports version `1.0.0` in package, health and OpenAPI metadata.
`GET /health` is local and requires no upstream client or OAuth-state access.
`GET /v1/snapshot` returns `McpSnapshotV1`, normalized schema `1.0`.
`GET /v1/budget`, `/v1/spending-search` and `/v1/goals` provide optional reads.
Other API majors have no routes or redirects.

If `FINARY_BRIDGE_API_KEY` is nonempty, an exact constant-time `X-API-Key` match is
required before constructing the native client, opening state or performing I/O.
Normal routes never bootstrap authorization. Errors use fixed
`{error: {code, message, retryable}}` envelopes; request errors and access logs
must not expose query labels, malformed values or upstream responses.

Official OAuth verifies issuer `https://clerk.finary.com` and allowlisted
endpoints. Explicit operator consent uses public-client registration and
S256 authorization code flow through the pinned SDK. One bridge process owns
one state on a local filesystem. The bridge-only `finary_mcp_data` volume holds
registration metadata, refresh token, effective scope and rotation generation;
access tokens stay in memory. Directory/file modes are 0700/0600. Atomic writes,
CAS checks and session leases prevent stale replacement and overlapping renewal.
Remote token rotation and local persistence cannot be made transactional. See
[Operations](operations.md#oauth-lifecycle-and-recovery) for recovery limits.
`n8n_data` and its encryption key are separate from Finary state.

## Synchronization and reading

The inactive workflow has manual and 07:30 Europe/Paris triggers. It creates a
UUID-bearing execution identity, fetches `/v1/snapshot` and the canonical schema,
validates them, reads all headers and rows, and checks writer control. Every
retained automated row must pass its schema and match exactly one stored
terminal. Manual inputs receive read-only key/type validation, with formulas
allowed only in notes. Every prepared batch is validated before portfolio writes.

Complete collection evidence alone permits current-row inactivation. Inactive
rows retain their observation/timestamps and are not rewritten again merely
because they remain absent. Accepted history is immutable, including distinct
observations on one business date. Empty branches continue once without dummy
rows. Decimal text is written RAW; empty strings explicitly clear nullable cells.

Success is written after required batches and writer/execution/terminal rechecks.
The same graph owns sanitized failure telemetry. A lost terminal response cannot
replace stored success. Valid FAILED terminals qualify partial rows for recovery;
orphan rows block reuse. Reads, writes and rechecks are sequential, not atomic.
The operating model therefore requires one writer and excludes overlapping
manual and scheduled executions.

The production consumer validates the complete physical inventory before choosing
an observation: headers, metadata, schemas, keys, terminal membership, counts,
references and financial semantics. Dated fallback can use independently valid
history without borrowing later account metadata. The consumer is executable
operator tooling; uploading instructions does not install it inside ChatGPT.

## Contract ownership

Application `1.0.0` identifies the installed service. API `1.0` identifies
normalized HTTP responses. Workbook `1.0` identifies physical sheets and metadata.
Source contract `1.0.0` identifies project-owned source interpretation. Each
advances according to its own compatibility impact; matching initial versions
do not require perpetual lockstep.

`docs/finary-mcp-contract.json` owns normalized definitions and `current_workbook`.
Generators produce models, the canonical workbook schema, identical packaged
contracts and the self-contained n8n export. Exact layout validation accompanies
version validation. Relabeling an incompatible workbook does not make it valid.
Fresh initialization creates a new workbook; no conversion is implemented.

Official overview totals and allocation are independently authoritative. Native
amounts, proven EUR values, full/direct ownership, buying-price basis and distinct
retrieval/valuation/debt/semantic/freshness coverage must survive every boundary.
The [source contract](finary-mcp-contract.md) and [data model](data-model.md)
describe these rules. Live availability and independent operator verification
remain separate from synthetic test success.
