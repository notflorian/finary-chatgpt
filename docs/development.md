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
  finary-bridge/tests/test_n8n_zero_position_runtime.py \
  finary-bridge/tests/test_restore_run_identity_runtime.py \
  finary-bridge/tests/test_sheets_connector_runtime.py \
  finary-bridge/tests/test_mcp_runtime.py
```

The n8n validator imports all three workflow exports into an isolated ephemeral n8n
instance with no network and no persistent project volumes. The import script pulls the
image pinned by `docker-compose.yml` before running network-disabled containers.
Use an otherwise unset/synthetic Compose environment; `COMPOSE_ENV_FILES` avoids
loading the local `.env`. No project container or volume is used.

The runtime regression separately imports a synthetic copy and executes the real
n8n graph with its persisted execution identity in disposable containers. Only
HTTP/Sheets I/O nodes are replaced; production Code/If nodes, connections,
empty-read flags, all-row writes, retry counts/delays, and finalization remain.
It covers header-only reads, zero position/history/liability branches,
liquidation, normal nonempty writes, and exhausted write retries preventing
success. The same required runtime file also covers four malformed required-field
snapshots, a corrupt retained liability selected for inactivation, and controlled
history/daily output faults injected immediately before the real all-batch gate.
Only those last two fault cases modify preparation to inject the synthetic
defect; its validator and the remaining graph stay intact. These executions
prove that an invalid later batch prevents the first portfolio write and terminal
success. It checks execution data for single continuation, real row counts,
write order and terminal timing, then checks the resulting synthetic workbook.
This is runtime evidence distinct from an import or individual Code-node test;
it does not test the Google service or upstream completeness beyond fixtures.
Without Docker/the pinned image, normal tests skip these cases; the explicit
`FINARY_REQUIRE_N8N_RUNTIME=1` check and CI fail instead of silently skipping.

The connector regression loads the installed `appendOrUpdate.execute` and
`GoogleSheet` implementation from that same Compose-pinned image. It executes
the exported preparation and finalization code with synthetic snapshots, then
applies the actual connector's emitted updates to individual in-memory cells.
Only Sheets I/O is replaced; update preparation, column addressing, exported
mapping expressions and append conversion remain real. A network-disabled Node
process is reused within each test worker; no n8n server, database, credentials
or project volumes are needed. This required gate covers all eight write paths,
known/null transitions, same-day history, retries, zero/false preservation and
consumer acceptance. The MCP connector cases cover native exact-decimal
null → zero → null transitions and accepted observation membership.

When `pytest-xdist` runs with `-n auto`, worker count comes from
`tests/conftest.py`: local runs default to `2`, while CI scales to available CPU
capacity (capped at `4`). Set `PYTEST_XDIST_WORKER_COUNT=<N>` to force an exact
worker count in both local and CI environments.
The required runtime gate uses CPU-detected `pytest-xdist` worker processes,
capped at four, on the same runner after the image has been pulled and all
exports have been imported. This uses all four CPUs on the public repository's
standard Ubuntu runner while reducing concurrency on smaller machines. The cap
also bounds simultaneous n8n containers on larger development machines.
Tests retain separate temporary directories and fresh network-disabled
containers/SQLite databases, including executions within a single test. Work
stealing balances cases with different numbers of engine executions; it does
not change the workflow graph or its real retry delays. The normal Python suite
remains serial. A worker crash fails the gate without restarting that worker.
The slowest 15 test phases are reported to make later timing changes visible.
For a serial comparison on the same runner and image, replace
`-n auto --maxprocesses 4` with `-n 0` and `--dist worksteal` with `--dist no`;
for the previous two-worker baseline, replace it with `-n 2`. Compare pytest
summaries and test counts as well as the total job duration. The job includes import checks
and engine execution, so its duration is not an import-only benchmark.

The restore-identity module also executes the daily graph in fresh disposable
SQLite databases that reuse execution number `1`, with real cryptographic UUIDs.
It covers interrupted and completed writes, every collision gate, and native
terminal-response-loss retries with an identical finalized payload. The installed
pinned n8n error dispatcher receives the real synthetic execution result; only
its delivery service is intercepted to capture the actual Error Trigger payload.
That payload and the saved execution feed the real exported error Code/If graph,
with synthetic local API/Sheets I/O and a manual input driver. Replays, failures
before writes, lost successful responses and mismatched source context are
checked. This verifies dispatcher fields and graph behavior, not live trigger
scheduling, public API authentication, Google transport, or a database backup
restoration. Python workbook regressions simulate restoration by ID reuse;
fresh-container engine tests prove new-installation ID reuse separately.

## Planned MCP contract validation

The [official MCP contract](finary-mcp-contract.md) is documentation and
executable schema evidence only. With the development dependencies installed,
run `python -m pytest -q tests/test_finary_mcp_contract.py` from `finary-bridge`.
The tests use Draft 2020-12 validation plus focused cross-field contract checks
on synthetic fixtures. They do not implement or prove a client, normalizer,
writer, OAuth lifecycle or migration engine. The full required gates above
remain applicable.

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
The legacy exports are frozen pending workbook removal. Their removed Pydantic
API generator and model-parity tests are not part of supported generation.
Static workbook and engine regressions remain until that cleanup. Shared helpers
in legacy-named tests still serve the MCP runtime gate; keep them importable.

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

The breaking application version is 2.0.0; API/workbook remain 3.0 and
source-contract remains 1.1.0. Workbook self-containment, migration/legacy-writer
removal, broader test consolidation and the documentation rewrite must finish
before release. Require all five CI jobs on the exact release commit. A package
build, tag or green CI does not authorize deployment, workflow activation or
operator data changes. This cleanup does not publish or tag a release.

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
`test_mcp_migration.py` exercises native Google request generation, preservation,
idempotence and lost-response handling against a fake HTTP peer. This does not
claim a live Google migration.

The normal credential-free suite and explicit required runtime command must both
pass. Runtime skips in the former are not runtime evidence. CI includes the MCP
runtime module and Python 3.12/3.14 SDK/auth compatibility. The narrow live module
requires explicit isolated state and is excluded from ordinary CI; use the
[operator runbook](mcp-operations.md). Record current execution results in the
[acceptance matrix](mcp-acceptance.md), separately from public metadata, actual
consent and shadow-workbook evidence.
