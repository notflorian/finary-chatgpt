# Finary Portfolio Data

Keep an auditable portfolio workbook for analysis in ChatGPT:

```text
Official Finary MCP → local bridge → n8n → private Google Sheets → ChatGPT
```

The bridge collects official overview totals and qualified account/holding detail.
n8n validates each observation before writing it, preserves financial history and
leaves your manual inputs under your control. Finary authorization stays in the
bridge; Google authorization stays in n8n.

## Before you start

You need Git, Docker Compose with a running Docker daemon, Python 3.12 or newer,
a local browser, official Finary MCP access, and a Google account able to use
Sheets and Drive APIs. Installation also needs a Google Cloud OAuth client for
n8n and, later, a private Google Drive connection in ChatGPT.

```bash
git clone https://github.com/notflorian/finary-chatgpt.git
cd finary-chatgpt
```

Follow the single [guided installation path](docs/operations.md#guided-fresh-installation).
It covers explicit Finary consent, safe OAuth-state handoff, Google consent, a
fresh paused workbook, one manual synchronization, native readback, and only
then optional scheduling and ChatGPT connection.

For development, generators, tests, CI, and diagnostics, see
[Development](docs/development.md). For workbook semantics and limits, use the
[data model](docs/data-model.md) and [MCP contract](docs/finary-mcp-contract.md).

## References

- [Operations](docs/operations.md): guided installation, monitoring, backup, and recovery.
- [Architecture](docs/architecture.md): components and trust boundaries.
- [ChatGPT](docs/chatgpt.md): connection and reading workflow.

[MIT License](LICENSE).
