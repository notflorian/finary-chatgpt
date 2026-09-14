# Development

## Local environment

Use Python 3.12 or newer for the bridge. Node.js 22.23.2 is the supported
runtime for executable workflow tests. From the repository root:

```bash
cd finary-bridge
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

The application uses FastAPI, Pydantic v2, Uvicorn and the pinned native MCP SDK.
Keep source-specific dependencies inside the adapter boundary.

Run the bridge without Docker:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

`GET /health` requires no credentials. Snapshot routes require the environment
described in `.env.example` unless a fake adapter is injected in tests.

Set `FINARY_MCP_STATE_PATH` only to independently authorized, protected OAuth
state. No provider selector or private credentials are used. Follow the
[OAuth runbook](mcp-operations.md#backups-and-independent-oauth). Health and
OpenAPI access require no OAuth state; routes never initiate consent.

## Required local checks

Run normal tests and static analysis from `finary-bridge`:

```bash
python -m pytest --collect-only -q
python -m pytest -m "not live" --ignore=tests/live
python -m ruff check .
python -m mypy app
python -m build
```

Run repository contracts from the repository root:

```bash
python scripts/validate-json.py
python scripts/build-workflow-validation.py --check
COMPOSE_ENV_FILES=/dev/null docker compose config --quiet
COMPOSE_ENV_FILES=/dev/null bash scripts/validate-n8n-imports.sh
FINARY_REQUIRE_N8N_RUNTIME=1 python -m pytest -q -n auto --maxprocesses 4 --dist worksteal --max-worker-restart 0 --durations=15 \
  finary-bridge/tests/test_n8n_runtime_support.py \
  finary-bridge/tests/test_mcp_runtime.py
```

The import check loads the single inactive MCP export into a disposable,
network-disabled container with no persistent project volumes or credentials.
Normal tests may skip Docker cases when unavailable; the explicit required gate
and CI fail instead. Run the isolated Compose check with synthetic configuration:

```bash
COMPOSE_ENV_FILES=/dev/null FINARY_MCP_TEST_DIR=/tmp \
FINARY_MCP_CANDIDATE_API_KEY=synthetic-key FINARY_MCP_CANDIDATE_WORKBOOK_ID=synthetic-book \
docker compose --env-file /dev/null -p finary-mcp-candidate -f docker-compose.mcp-test.yml config --quiet
```

Keep evidence boundaries distinct:

- Contract/unit tests exercise normalized models, monetary semantics, coverage,
  the fresh initializer and the consumer.
- `n8n_code.py` executes individual exported Code nodes with synthetic context.
- `validate-n8n-imports.sh` proves the export imports into pinned n8n.
- `n8n_runtime.py` executes the actual graph with persisted execution IDs, Code/If
  nodes, retries and terminal paths, replacing external I/O only. Complete CLI
  output is captured through files with the execution exit status preserved.
- `sheets_connector.py` runs the installed Sheets read and appendOrUpdate operations
  and GoogleSheet implementation; fake transport preserves cell types/formulas and
  applies the emitted updates.
- The end-to-end runtime regression starts with the real fresh initializer,
  obtains a snapshot through synthetic MCP and the FastAPI route, executes the
  exported graph, applies connector-emitted operations and invokes the production
  reference consumer. It never manufactures successful output rows separately.

Runtime cases cover nonempty/zero/partial holdings, repeated empty runs, manual
formulas, exact decimal bounds, null → zero → null cells, exhausted retries and
recovery, invalid later batches, control rechecks, UUID identities, terminal
response loss and complete stdout evidence under backpressure.

The required runtime gate uses `-n auto --maxprocesses 4 --dist worksteal` with
`--max-worker-restart 0`. Local worker count defaults to two; CI uses detected
capacity capped at four. `PYTEST_XDIST_WORKER_COUNT` provides an explicit override.
Each engine execution uses fresh disposable network-disabled containers/databases.
These are synthetic runtime checks, not live Google or Finary acceptance.

## Workflow validation maintenance

The common entry point generates and checks all supported MCP artifacts:

```bash
python scripts/build-workflow-validation.py
python scripts/build-workflow-validation.py --check
python -m pytest -q finary-bridge/tests/test_mcp_integration.py finary-bridge/tests/test_mcp_workflow.py
```

It invokes the model/packaged-contract, workbook and workflow generators and
propagates every failure. MCP Code-node sources live under
`n8n/code-nodes/finary-mcp-sync`; exports are self-contained for pinned n8n.
Shared engine, Code-node and connector helpers live in `tests/n8n_runtime.py`,
`tests/n8n_code.py` and `tests/sheets_connector.py`; none loads another writer.
The initializer and packaged schema are verified alongside generated artifacts.

## Test design

The normal suite is deterministic and credential-free:

- adapter tests use fake HTTP sessions and application-level exception checks;
- MCP adapter/service tests use synthetic anonymized fixtures;
- HTTP tests retain the authorization dependency and client factory, replacing
  only transports with synthetic peers;
- schema tests compare stable models, JSON definitions, and documented
  semantics;
- workflow tests execute exported n8n Code-node JavaScript in Node.js and check
  the surrounding graph;
- operations and Compose tests verify isolation, timeouts, retries, inactive
  exports, and secret-free configuration.

Never make the normal suite contact Finary, Google, GitHub, or another public
service. Do not commit recordings of real portfolio traffic. When a new upstream
shape is needed, create an anonymized fixture directly: replace IDs, names,
institutions, values, account details, and correlation data while retaining only
the necessary structure.

## Opt-in live MCP checks

Normal CI excludes live diagnostics. They require explicit isolated operator
OAuth and sanitized structural output. See the [MCP runbook](mcp-operations.md).
No private password/MFA/session tests or commands remain.

## Continuous integration

`.github/workflows/ci.yml` runs on pull requests and pushes to `main` with
read-only repository permissions. It has five bounded jobs:

| Job | Checks |
| --- | --- |
| `tests` | Python 3.12 normal pytest suite, explicitly excluding live tests |
| `mcp-validation-python314` | Python 3.14 MCP SDK/OAuth, HTTP boundary, optional endpoints and exact decimals |
| `static-analysis` | Ruff and strict mypy for `app` |
| `repository-contracts` | JSON parsing and resolved Compose validation |
| `n8n-import` | isolated imports and required synthetic workflow executions using pinned n8n |

Actions are pinned to immutable revisions, runtime versions are explicit, and
the workflow does not read repository secrets, start the live stack, upload
portfolio artifacts, or publish n8n workflows. A green CI run validates the
repository artifacts; it does not prove that external credentials, Finary, or
Google Sheets are available.

The `n8n-import` CI job pre-pulls the Compose-pinned n8n image before isolated
runtime regression execution so parallel workers reuse a warm local image cache.

## Change checklist

Before submitting a change:

1. keep Finary-specific behavior inside the adapter;
2. preserve MCP API/workbook contracts and fixed source provenance;
3. update `docs/google-sheets-schema.json`, workflows, tests, and documentation
   together for a workbook contract change;
4. keep workflow exports credential-free and inactive;
5. run all checks relevant to the change;
6. inspect `git diff` and `git status`;
7. search changed files for secrets, personal financial data, raw payloads, and
   broken documentation links.

Do not weaken coverage, currency, null, identity, or idempotency rules to make a
test pass.

## Preparing application 2.0.0

Application 2.0.0, API 3.0, workbook 4.0 and source-contract 2.0.0 have distinct
purposes. The workbook change is breaking and requires fresh installation.
Broader test consolidation and historical-document cleanup remain release work.
Require all five CI jobs on the exact release commit. A package build or green
CI does not authorize deployment, workflow activation or operator data changes.

## Official MCP evidence boundaries

The bridge pins `mcp==2.2.0` (MIT, Python >=3.10; project >=3.12), using its v2
`Client`, Streamable HTTP and OAuth provider APIs. No v1 SDK examples are used.
`test_mcp_integration.py` feeds synthetic upstream responses through real SDK
initialization, discovery, tools, adapter, service and protected API boundaries.
`test_mcp_auth.py` exercises supported SDK OAuth with disposable stores and fake
HTTP, including restart, expiry, revoked refresh, concurrent leases, rotation
and explicit isolated revocation. These are synthetic authorization proofs.

Model/workbook/workflow generators are included in the existing parity command.
The packaged `app/mcp-contract.json` must equal the reviewed source contract;
wheel installation includes it. `test_mcp_workflow.py` validates exported code,
while `test_mcp_runtime.py` separately runs the actual pinned graph and installed
Sheets connector with synthetic I/O. It verifies native decimal null/zero/blank
updates, child tables, terminal sequencing and the production reference consumer.
Fresh creation request generation and current native-cell decoding are tested
with synthetic inventories. No test in the normal gate contacts Google, Finary
or Clerk, or mounts production volumes.
