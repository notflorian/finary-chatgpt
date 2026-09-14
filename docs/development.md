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
[OAuth runbook](operations.md#independent-mcp-oauth). Health and
OpenAPI access require no OAuth state; routes never initiate consent.

## Required local checks

Run normal tests and static analysis from `finary-bridge`:

```bash
python -m pytest --collect-only -q
python -m pytest -m "not live" --ignore=tests/live -n auto --maxprocesses 4 --dist worksteal --max-worker-restart 0 --durations=15
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

Both full tests and the required runtime gate use bounded xdist with no worker
restart. Local worker count defaults to two; CI uses detected capacity capped at
four. `PYTEST_XDIST_WORKER_COUNT` is an explicit override. Each engine execution
uses fresh disposable containers/databases; synthetic checks do not establish
live Google, Finary or Clerk behavior.

## Workflow validation maintenance

The common entry point generates and checks all supported MCP artifacts:

```bash
python scripts/build-workflow-validation.py
python scripts/build-workflow-validation.py --check
python -m pytest -q finary-bridge/tests/test_mcp_contract.py finary-bridge/tests/test_mcp_integration.py finary-bridge/tests/test_mcp_workflow.py
```

It invokes the model/packaged-contract, workbook and workflow generators and
propagates every failure. MCP Code-node sources live under
`n8n/code-nodes/finary-mcp-sync`; exports are self-contained for pinned n8n.
Test modules import focused support modules, never other test modules:

- `tests/mcp_artifacts.py` loads canonical artifacts and materializes fresh synthetic cases.
- `tests/mcp_wire.py` and `tests/mcp_auth_peer.py` provide native MCP and OAuth peers.
- `tests/mcp_snapshots.py` supplies a fixed clock and real-service snapshot construction.
- `tests/mcp_workbooks.py` prepares fresh inventories and executes exported Code nodes;
  `tests/mcp_inputs.py` supplies independent typed manual inputs.
- `tests/n8n_runtime.py`, `tests/n8n_code.py` and `tests/sheets_connector.py` retain
  separate engine, individual Code-node and installed connector execution boundaries.

`test_mcp_contract.py` compares JSON Schema and production model outcomes with
checked-in expectations. Focused semantic tests call production validators;
`test_mcp_workflow.py` independently checks exported JavaScript against the same
literal outcomes. Native pagination/result wrappers and optional date requests
are exercised at their production boundaries. Declared capability evidence is
metadata only and does not certify upstream support. Support code is excluded
from the application package.
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

## Opt-in diagnostics

Live diagnostics require explicit operator authorization for a designated isolated
connection/workbook. They are not part of setup or ordinary CI. Use the development
environment above, disposable state outside the checkout, and stop all other
owners before a host test. [OAuth setup](operations.md#independent-mcp-oauth) and
[recovery limits](operations.md#oauth-lifecycle-and-recovery) still apply.

From the repository root, authorize a fresh isolated state and retain its path:

```bash
cd finary-bridge
umask 077
export FINARY_MCP_TEST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/finary-mcp-test.XXXXXX")"
python -m app.mcp_auth bootstrap --state "$FINARY_MCP_TEST_DIR/oauth.json"
FINARY_MCP_LIVE_TEST=1 FINARY_MCP_LIVE_ISOLATED_STATE=1 \
FINARY_MCP_LIVE_STATE_PATH="$FINARY_MCP_TEST_DIR/oauth.json" \
python -m pytest -q -s --tb=no -m live \
  tests/live/test_mcp_live.py::test_isolated_native_collection_structure
```

`STRUCTURAL_COLLECTION_VALIDATED` reports bounded native collection, not workbook
writes. On failure, an explicitly authorized repeat with
`FINARY_MCP_LIVE_DIAGNOSTICS=1` prints only allowlisted stage/tool/path/type
information. It never prints instance values, raw payloads or authentication data.

The standalone `docker-compose.mcp-test.yml` uses project `finary-mcp-candidate`,
localhost ports 8001/5679, its own network/n8n volume and an existing isolated
OAuth directory. Use it alone, never as a production override. Export
`FINARY_MCP_TEST_DIR`, `FINARY_MCP_CANDIDATE_API_KEY`,
`FINARY_MCP_CANDIDATE_WORKBOOK_ID`, `FINARY_MCP_CANDIDATE_WRITER_ID` and
`FINARY_MCP_CANDIDATE_WRITER_GENERATION` explicitly for its fresh isolated workbook
in the operator's shell. Keep the independently authorized OAuth directory and
matching writer values. Stop all other users of that state before container use.
From the repository root, in that same shell, an explicitly authorized operator
can validate those settings without printing resolved secrets and then start only
the isolated stack:

```bash
COMPOSE_ENV_FILES=/dev/null docker compose --env-file /dev/null \
  -p finary-mcp-candidate -f docker-compose.mcp-test.yml config --quiet && \
COMPOSE_ENV_FILES=/dev/null docker compose --env-file /dev/null \
  -p finary-mcp-candidate -f docker-compose.mcp-test.yml up -d --build --wait
```

Both commands inherit the five exported values; neither loads production `.env`
files. Do not copy the synthetic assignments from Required local checks into this
operator command. Create its own Google credential. Keep its workflow unpublished
and stop it with the same environment/project/file arguments and `stop` instead
of `up -d --build --wait`; never mount production volumes or use `down -v`.

Natural-expiry diagnostics retain one OAuth session across the SDK-advertised
expiry and perform two bounded collections. They neither change tokens/clocks nor
probe intentional reuse of expired tokens. Stop the isolated bridge and run from
`finary-bridge` with the isolated state path:

```bash
FINARY_MCP_LIVE_TEST=1 FINARY_MCP_LIVE_ISOLATED_STATE=1 \
FINARY_MCP_LIVE_EXPIRY_TEST=1 \
FINARY_MCP_LIVE_STATE_PATH="$FINARY_MCP_TEST_DIR/oauth.json" \
python -m pytest -q -s --tb=no -m live \
  tests/live/test_mcp_live.py::test_isolated_natural_expiry_renewal
```

The default maximum wait is 7,200 seconds;
`FINARY_MCP_LIVE_EXPIRY_MAX_WAIT_SECONDS` may explicitly raise it to at most 86,400.
Missing/already elapsed/out-of-bound expiry fails. A structural countdown occurs
at most every 30 seconds. Only NATURAL_EXPIRY_RENEWAL_VALIDATED establishes this
session's advertised expiry/renewal; it does not guarantee indefinite consent.

Revocation is destructive to its **separate disposable grant**. Create and authorize
a dedicated directory before the test; never use the ordinary isolated bridge's
state and do not invoke revoke first. Run from `finary-bridge`:

```bash
export FINARY_MCP_REVOCATION_TEST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/finary-mcp-revocation.XXXXXX")"
python -m app.mcp_auth bootstrap --state "$FINARY_MCP_REVOCATION_TEST_DIR/oauth.json"
FINARY_MCP_LIVE_TEST=1 FINARY_MCP_LIVE_ISOLATED_STATE=1 \
FINARY_MCP_LIVE_REVOKE_DISPOSABLE=1 \
python -m pytest -q -s --tb=no -m live \
  tests/live/test_mcp_revocation_live.py::test_disposable_server_revocation
```

Only HTTP 400 `invalid_grant` establishes remote refresh rejection. Access-token
acceptance is reported separately: local deletion or accepted revoke does not
prove immediate remote access rejection. Failed probes do not authorize new
consent or automatic retries. No portfolio tools are called by this test.

For opt-in Google Sheets diagnostics, generate inactive synthetic workflows from
the root with development dependencies installed:

```bash
python scripts/build-mcp-live-scenarios.py --workbook-id "$DISPOSABLE_SHEET_ID" \
  --output /tmp/mcp-live-scenarios.json
```

Use a new schema-1.0 workbook with ACTIVE control for `synthetic-live-writer`,
generation 1, and an isolated n8n Google credential. There are no Finary HTTP nodes
or schedule. `interrupt` intentionally stops after the first account write,
leaving an orphan with no terminal; readback and reuse must be rejected. Preserve
that workbook as failed diagnostic evidence. Generate a **second set for a new
blank workbook**, and execute only `null`, `known`, then `clear`, each once.
Verify null → exact `123.123456789012345678901234` text → blank native amount
cells, immutable observation history and unique terminal membership through
[full readback](operations.md#consumer-readback-verification). Do not interpret
this hard stop as recoverable FAILED telemetry. Handled-error recovery is
separately tested in the mandatory synthetic runtime gate. Clear cached data
before reads, regenerate UUIDs for a new diagnostic series and return disposable
control to PAUSED afterwards. Offline generation alone is not live verification.

## Continuous integration

`.github/workflows/ci.yml` runs on pull requests and pushes to `main` with
read-only repository permissions. It has five bounded jobs:

| Job | Checks |
| --- | --- |
| `tests` | Python 3.12 normal pytest suite, explicitly excluding live tests |
| `mcp-validation-python314` | Python 3.14 contract/model, MCP SDK/OAuth, HTTP boundary, optional endpoints and exact decimals |
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

## Version and package checks

Application and source contract use semantic versions (`1.0.0`); API and workbook
use schema versions (`1.0`). They are independently versioned. Change source
contracts and generators first, then regenerate all artifacts. Never edit packaged
JSON, generated models or embedded workflow code independently.

A clean wheel/sdist must contain the current byte-identical contracts and exclude
tests/support scripts. Smoke-test installed health, OpenAPI and initializer outside
the checkout. The pinned `mcp==2.2.0` SDK, protocol revision, storage format and
writer generation are unrelated version domains; do not change them as part of
an application/schema update. CI success does not authorize publication,
deployment, workflow activation or changes to operator data.
