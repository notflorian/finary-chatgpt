# Finary Portfolio Data

Keep an auditable portfolio workbook for analysis in ChatGPT:

```text
Official Finary MCP → local bridge → n8n → private Google Sheets → ChatGPT
```

The bridge collects official overview totals and qualified account/holding detail.
n8n validates each observation before writing it, preserves financial history and
leaves your manual inputs under your control. Finary authorization stays in the
bridge; Google authorization stays in n8n.

## Requirements and setup

Use a local machine with Docker Compose, Python 3.12+, Git and a browser for
independent Finary OAuth consent. You also need access to official Finary MCP,
a Google account with Sheets and an OAuth client for n8n. ChatGPT needs a private
Google Drive connection capable of reading the workbook.

```bash
git clone https://github.com/notflorian/finary-chatgpt.git
cd finary-chatgpt
```

Follow [Operations](docs/operations.md#install-and-configure) in order:

1. Install the bridge tools, configure `.env` and authorize independent MCP OAuth.
2. Place the protected state in the bridge-only volume and start the local stack.
3. Authorize Google in n8n, generate and create a fresh workbook, then match its
   writer ID/generation and explicitly change its control from PAUSED to ACTIVE.
4. Import the inactive workflow, bind its Google credential and run one complete
   manual synchronization. Validate full readback before publishing its schedule.
5. Connect the private workbook and [interpretation reference](docs/finary-portfolio-data-knowledge.md)
   to ChatGPT using the [reading guide](docs/chatgpt.md).

The first synchronization is verified by a unique successful terminal and the
production consumer's complete-current readback, not merely a green n8n node.
The schedule runs at 07:30 Europe/Paris after operator publication.

## API and contracts

Application **1.0.0**, source contract **1.0.0**, normalized API **1.0** and workbook
**1.0** have distinct version purposes. The current MCP endpoints are:

- `GET /health`: local metadata, without OAuth-state or upstream access.
- `GET /v1/snapshot`: official overview and qualified portfolio detail.
- `GET /v1/budget`, `/v1/spending-search`, `/v1/goals`: optional on-demand reads.

All MCP routes use optional local `X-API-Key` protection. Unsupported API majors
return 404 without redirects or upstream access. Installation uses the checked-out
source and matching generated artifacts; these instructions do not select a
published tag.

## Limits

One local stack owns one writer and one fresh workbook. No workbook conversion is
provided; existing operator data is left untouched. Sequential Sheets operations
are not atomic. Official totals and allocation remain authoritative even when
detail is unavailable. Debt detail, speculative FX, company look-through,
transaction ingestion and investment-performance calculation are unavailable.
Unknown amounts remain unknown; qualified ownership and valuation are disclosed.
Budget/search/goals never run in scheduled portfolio collection. This product
performs no trading.

## References

- [Architecture](docs/architecture.md): components and trust boundaries.
- [Data model](docs/data-model.md): tables, observations and analytical concepts.
- [Operations](docs/operations.md): complete setup, monitoring, backup and recovery.
- [Development](docs/development.md): dependencies, generators, tests and CI.
- [MCP contract](docs/finary-mcp-contract.md): source evidence and validation rules.
- [ChatGPT](docs/chatgpt.md): connection and reading workflow.

[MIT License](LICENSE).
