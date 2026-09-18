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

Package and image implementation details: the package build stages the root MIT
notice automatically. Compose builds from the repository root using
`finary-bridge/Dockerfile`; `.dockerignore` limits inputs to package sources,
configuration, and the notice. For a direct image build, run
`docker build -f finary-bridge/Dockerfile .` from the repository root.

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

## Optional Spec Kit workflow

Spec Kit 1.0.8 is initialized for Codex but remains optional. Keep routine work
direct: issue → implementation → relevant tests → pull request. Use Spec Kit when
a feature benefits from durable requirements, design, task breakdown, or
cross-artifact review.

Initialize or amend the active
[constitution](../.specify/memory/constitution.md) with `$speckit-constitution`
before using `$speckit-plan` or `$speckit-analyze`; those commands treat its
principles as non-negotiable. Start an optional feature workflow with
`$speckit-specify`, then use `$speckit-clarify`, `$speckit-plan`,
`$speckit-tasks`, `$speckit-analyze`, `$speckit-implement`, or
`$speckit-converge` as useful. `$speckit-checklist` and
`$speckit-taskstoissues` provide targeted follow-ups.

`$speckit-specify` stores feature context in its resolved feature directory
(by default `specs/<feature>/`) and records the active directory in
`.specify/feature.json`; this context is independent of Git branch names. The
constitution summarizes durable governance only. `AGENTS.md`, the canonical
contracts, and the maintained guides remain the sources for detailed project rules,
commands, and operations.

## Required local checks

Run normal tests and static analysis from `finary-bridge`:

```bash
python -m pytest --collect-only -q
python -m pytest -m "not live" --ignore=tests/live -n auto --maxprocesses 4 --dist worksteal --max-worker-restart 0 --durations=15
python -m ruff check .
python -m mypy app
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
FINARY_REQUIRE_OAUTH_DOCKER=1 python -m pytest -q finary-bridge/tests/test_mcp_oauth_docker.py
```

CI runs the normal suite in two deterministic weighted shards. The local command
above intentionally remains unsharded. Validate that both CI partitions are
nonempty, disjoint and complete with:

```bash
python scripts/validate-pytest-shards.py
```

The import check loads the single inactive MCP export into a disposable,
network-disabled container with no persistent project volumes or credentials.
Normal tests may skip Docker cases when unavailable; the explicit required gate
and CI fail instead. Run the isolated Compose check with synthetic configuration:

```bash
COMPOSE_ENV_FILES=/dev/null FINARY_MCP_TEST_DIR=/tmp \
FINARY_MCP_CANDIDATE_API_KEY=synthetic-key FINARY_MCP_CANDIDATE_WORKBOOK_ID=synthetic-book \
FINARY_MCP_CANDIDATE_UID=1001 FINARY_MCP_CANDIDATE_GID=1001 \
docker compose --env-file /dev/null -p finary-mcp-candidate -f docker-compose.mcp-test.yml config --quiet
```

The OAuth Docker gate requires a rootful Linux daemon without user-namespace
remapping. Its diagnostic regression additionally requires a non-root host: it
builds the bridge image, resolves the candidate identity/bind mount, rejects the
original root identity, rotates fabricated state through the fake OAuth transport,
and verifies host recovery. A separate regression runs the fresh-install helper
against a unique Compose project and bridge-only named volume, then independently
checks exact content, generation, root ownership and 0700/0600 modes while the
bridge remains stopped. Execution containers have no network and cleanup targets
only their synthetic directories, images and uniquely named volumes. The required
gate fails when this runtime is unavailable; on other local platforms, obtain that
evidence from the `oauth-ownership` CI job.

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

Full tests, Python 3.14 compatibility and the required runtime gate use bounded
xdist with no worker restart. Local worker count defaults to two. The full CI gate
sets four workers; other CI gates use detected capacity capped at four.
`PYTEST_XDIST_WORKER_COUNT` is an explicit override. Each engine execution
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
propagates every failure. The five handwritten MCP Code-node sources (Initialize,
Validate, Prepare, Finalize Success and Finalize Failure) live under
`n8n/code-nodes/finary-mcp-sync`. Shared validation remains in `n8n/mcp-validation.js`
and `n8n/mcp-workbook.js`. The workflow generator embeds mechanical Check, Select
and Continue nodes directly, without intermediate source files. The generated
`n8n/workflows/finary-mcp-sync.json` export is self-contained for pinned n8n;
`--check` detects final artifact drift without writing files.

The two shared sources use explicit `// @mcp-group <name>` / `// @mcp-end`
boundaries. The workflow generator's `GROUP_DEPENDENCIES` and `PROFILES` select
groups by node role and emit each dependency once, before its dependents. Keep
helper implementations in those canonical blocks and declare transitive needs,
including top-level initializers. Contract bindings precede the groups; Initialize
uses only its minimal contract, while Validate and Finalize Failure embed their
own schemas. Every other role retains its Validate schema binding and integrity
check, including Continue. When probing a helper, use an exported node that needs
it in production and supply that node's synthetic schema context.

The full source and packaged MCP contracts remain authoritative for bridge,
adapter and optional-tool validation. The workbook generator projects only the
transitive local-definition dependencies of workbook row bindings, column
constraints and the explicit JavaScript entry points in `DOWNSTREAM_ROOTS`.
Keep that small declaration aligned with named helper and enum lookups when
editing the shared JavaScript. References must use `#/$defs/<name>`; unsupported
or missing reachable references fail generation without fetching schemas.
Unused upstream definitions do not affect workbook or workflow bytes/digests.
Regenerate through the common entry point and follow the
[coordinated artifact adoption steps](operations.md#generated-artifact-adoption)
when the workbook digest changes.

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

For the bounded workbook-readback performance probe, run from the repository root:

```bash
finary-bridge/.venv/bin/python scripts/profile-workbook-readback.py
```

The synthetic probe covers 1, 10 and 100 retained observations through the actual
native consumer path. It reports rows, complete inventory passes, row validation,
schema metadata setup, terminal-identity comparisons and illustrative elapsed time.
Operation counts are regression evidence; elapsed time is informational and is not
a portable test threshold.

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
The supported ownership model is a non-root operator on rootful Linux Docker,
without user-namespace remapping. After host authorization, derive and export:

```bash
export FINARY_MCP_CANDIDATE_UID="$(id -u)"
export FINARY_MCP_CANDIDATE_GID="$(id -g)"
```

Only the candidate bridge uses this numeric UID/GID; no passwd entry is required.
The preflight rejects missing/non-numeric identities, root, mismatched identities,
and unsafe directories without repairing them. Keep directory mode 0700 and all
state, lock and lease files at 0600. Never authorize as root or change production
volume ownership. Health remains metadata-only: a healthy container does not prove
OAuth state is usable. Docker Desktop bind mounts and rootless/user-namespace
mappings have different ownership semantics; this Linux procedure does not certify
those platforms. Use host diagnostics there unless the complete synthetic handoff
has independently been verified for that environment.

From the repository root, in that same shell, an explicitly authorized operator
can validate those settings without printing resolved secrets and then start only
the isolated stack:

```bash
python scripts/validate-mcp-candidate.py && \
COMPOSE_ENV_FILES=/dev/null docker compose --env-file /dev/null \
  -p finary-mcp-candidate -f docker-compose.mcp-test.yml config --quiet && \
COMPOSE_ENV_FILES=/dev/null docker compose --env-file /dev/null \
  -p finary-mcp-candidate -f docker-compose.mcp-test.yml up -d --build --wait
```

The commands inherit all seven exported values; none loads production `.env`
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
read-only repository permissions. Superseded runs are cancelled only within the
same pull request; `main` runs are never cancelled by this policy. The stable
acceptance jobs remain:

| Job | Checks |
| --- | --- |
| `release-artifacts` | required fresh wheel/sdist installs, archive inventories, negative controls and actual bridge image smoke |
| `tests` | aggregate for both Python 3.12 normal-suite shards, explicitly excluding live tests and the separately required OAuth Docker case |
| `mcp-validation-python314` | Python 3.14 contract/model, MCP SDK/OAuth, HTTP boundary, optional endpoints and exact decimals |
| `static-analysis` | Ruff and strict mypy for `app` |
| `repository-contracts` | JSON parsing and resolved Compose validation |
| `oauth-ownership` | required diagnostic and fresh-install volume handoffs on rootful Linux using the actual bridge image |
| `n8n-import` | isolated import validation and required synthetic workflow executions using pinned n8n |

Actions are pinned to immutable revisions, runtime versions are explicit, and
the workflow does not read repository secrets, start the live stack, upload
portfolio artifacts, or publish n8n workflows. A green CI run validates the
repository artifacts; it does not prove that external credentials, Finary, or
Google Sheets are available.

The `n8n-import` acceptance gate aggregates two deterministic runtime shards and
a separate collection proof. Runtime shard zero import-validates first and then
reuses its Compose-pinned image; shard one independently pre-pulls that exact
image before its own tests. Both shards use four bounded xdist workers. The
aggregate uses `always()` and accepts only successful shards and collection
proof, so a cancelled, skipped or failed dependency cannot satisfy the required
check. Python setup caches dependency downloads keyed by
`finary-bridge/pyproject.toml`; every job still installs the current checkout
normally.

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

### Installed release artifacts

From the repository root, with Git, Python 3.12+ (including venv/pip), Docker Engine
and Compose available, run exactly:

```bash
python scripts/validate-release-artifacts.py
```

The command requires package-index access for fresh build/runtime dependency
resolution and base-image access. It uses a temporary directory outside the
checkout and no operator environment, state or production mounts. Docker is
required: unavailable Docker or any failed build/install/check exits nonzero,
including locally. Obtain missing platform evidence from the required
`release-artifacts` CI job; a local partial run is not a passing gate.

One wheel and one sdist are built with the declared minimum setuptools 77.0.3
in a separate builder environment. `MANIFEST.in` explicitly excludes tests even
with backends that automatically include test modules in sdists. Both archive
inventories, application files,
canonical JSON bytes and MIT metadata/notice are checked. Each exact archive is
installed with fresh runtime dependencies only in its own venv. The sdist build
uses pip isolation after the staging source has been removed. Python `-I`, clean
environments and explicit module/distribution path checks reject editable,
user-site, PYTHONPATH and checkout contamination. No dev extra is installed in
the tested environments. Controlled mutations of the wheel installation prove
missing contracts, license metadata/notice and checkout-only imports fail; a
restored installation passes again.

The same runtime-only smoke starts the real app with Uvicorn outside source
folders, checks health, exact OpenAPI routes, authentication, unsupported majors,
versions and offline PAUSED workbook/Google-create output. Profile and audit
sentinels are installed before app import to reject and persist attempted MCP
client construction, OAuth-store calls/state-file reads and outgoing socket/DNS
operations, including caught exceptions. Only the separate HTTP probe makes
loopback requests. Focused tests exercise the sentinels themselves.

The image check resolves the production Compose build configuration and builds
the actual Dockerfile. It runs the same smoke in `/tmp` with `--network none`,
then independently verifies health using the unmodified image startup command.
The image contains its installed application and notice; build sources are
removed to prevent import shadowing. Containers/images have unique names,
bounded execution and cleanup on success or failure. The separate Linux
`oauth-ownership` gate retains the candidate UID/GID host–container–host check.

For standalone packaging, `python -m build finary-bridge` from the root remains
supported (install the `build` frontend first), as does `python -m build` inside
`finary-bridge`. `setup.py` stages `finary-bridge/LICENSE` from the authoritative
root `LICENSE` when the tracked `.repository-source` marker identifies the source
layout; the generated copy is ignored by Git and included in the sdist. The marker
is excluded from the sdist, so an extracted distribution uses only its bundled
notice and rejects an incomplete archive instead of consulting ambient parent
files.
SPDX metadata requires the declared setuptools minimum; no license change is made.
Both Compose files now build from the repository root with an explicit
`finary-bridge/Dockerfile`. The root `.dockerignore` allowlists only that Dockerfile,
root notice, package configuration and application Python/JSON inputs, excluding
`.env`, OAuth state, Git history, tests and unrelated workspace files. Direct
image builds use `docker build -f finary-bridge/Dockerfile .` from the root.
