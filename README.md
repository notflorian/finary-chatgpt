# Finary Portfolio Data

Finary Portfolio Data is a local-first pipeline that turns a private Finary
portfolio into a stable Google Sheets data model that ChatGPT can analyze.

```text
Finary -> finary-bridge -> n8n -> Google Sheets -> ChatGPT
```

Application **2.0.0** supports official Finary MCP only. `/v3/snapshot` supplies
exact native amounts, authoritative overview/allocation and explicit coverage.
The private API adapter, password/session/MFA configuration and V1/V2 snapshot
routes have been removed. Neither Sheets nor ChatGPT receives Finary credentials
or raw upstream payloads.

This branch is part of the [next-major release preparation](https://github.com/notflorian/finary-chatgpt/issues/100).
Workbook self-containment and migration/legacy-writer removal remain under
[#102](https://github.com/notflorian/finary-chatgpt/issues/102); broader test and
documentation cleanup remain under #103 and #104. The retained legacy workflow
exports are frozen and cannot synchronize against this bridge. Do not activate
them. Existing operator data is untouched; the final major release requires a
fresh supported workbook, without conversion from workbook 2.1.

## Requirements

- Python 3.12+ for local bridge setup and independent MCP OAuth consent
- Docker Engine and Compose v2 for the local stack
- Finary access with independently authorized official MCP OAuth
- Google Sheets OAuth in n8n for workbook synchronization

## Bridge setup

```bash
git clone https://github.com/notflorian/finary-chatgpt.git
cd finary-chatgpt
cp .env.example .env
chmod 600 .env
```

Configure an optional `FINARY_BRIDGE_API_KEY`, a strong stable
`N8N_ENCRYPTION_KEY`, and the MCP workbook/writer variables from `.env.example`.
No provider selector or private Finary credentials are required.

The supported OAuth bootstrap uses a browser on the host. Install the bridge
with the [development setup](docs/development.md#local-environment), then follow
[independent OAuth setup](docs/mcp-operations.md#backups-and-independent-oauth).
The verified issuer is `https://clerk.finary.com`. Its OAuth endpoints remain
allowlisted; the removed private Clerk password/cookie/MFA flow is unrelated.
Do not reuse an assistant or plugin connection. Keep renewable state bridge-only,
with directory/file modes 0700/0600; access tokens remain in memory. For Compose,
follow the runbook's protected transfer or bind-mount procedure.

```bash
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8000/health
```

Expected response: `{"status":"ok","service":"finary-bridge","version":"2.0.0"}`.
Health requires no OAuth or network access. The bridge and n8n bind localhost.
An authorized snapshot without usable OAuth returns `503 MCP_AUTH_UNAVAILABLE`.

Use the [canonical workbook schema](docs/google-sheets-schema.json) and
`n8n/workflows/finary-mcp-sync.json` for the retained MCP writer. Keep imports
inactive; its writer ID/generation/control row must agree before a manual sync.
Workbook initialization is being simplified under #102; the existing
[operator runbook](docs/mcp-operations.md) contains transitional workbook
procedures, not a finished 2.0.0 installation guide. Release readiness also
requires the operator acceptance described there.

## ChatGPT

Use a private workbook connection and the [MCP consumer rules](docs/mcp-consumer.md).
The older workbook 2.1 knowledge reference is not the MCP contract. A newer failed
sync does not replace the latest validated success. Qualify detail, ownership,
currency, freshness and unavailable debt separately from official overview totals.

## API

- `GET /health`: local service metadata.
- `GET /v3/snapshot`: canonical MCP portfolio contract, API schema `3.0`.
- `GET /v3/budget`, `GET /v3/spending-search`, `GET /v3/goals`: optional reads.
- `/v1/snapshot` and `/v2/snapshot`: HTTP 404, absent from OpenAPI.

When `FINARY_BRIDGE_API_KEY` is nonempty, all MCP routes require an exact
`X-API-Key` match before client construction, OAuth-state access or network I/O.
Missing/invalid keys return `401 BRIDGE_AUTH_FAILED`; an unset/empty configured
key preserves the optional local protection behavior.

## Development

See [Development](docs/development.md) for all credential-free checks, package
builds and the required isolated pinned n8n/Sheets connector runtime gate.
Normal tests never contact Finary or Google; live diagnostics remain opt-in.

## Documentation

- [Architecture](docs/architecture.md): current bridge and trust boundaries.
- [MCP operations](docs/mcp-operations.md): OAuth and isolated operator acceptance.
- [MCP contract](docs/finary-mcp-contract.md): financial and transport semantics.
- [MCP consumer](docs/mcp-consumer.md): observation interpretation.
- [Operations](docs/operations.md): local service controls and retained workbook procedures.

## Security and limitations

Keep the bridge local. Independent OAuth state belongs only to the bridge;
Google OAuth belongs only to n8n. Do not back up renewable Finary state or delete
existing operator volumes during an upgrade. Unknown amounts remain null and
no speculative FX conversion is performed. Official overview totals and allocation
are authoritative; account and holding detail never replaces them. Optional reads
do not run during portfolio synchronization. Live production acceptance is a
separate operator action; this change does not deploy or activate anything.

## License

This project is available under the [MIT License](LICENSE).
