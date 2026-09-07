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

The application uses FastAPI, Pydantic v2, Uvicorn, and `curl-cffi`. Do not add a
direct Finary dependency outside the adapter boundary.

Run the bridge without Docker:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

`GET /health` requires no credentials. Snapshot routes require the environment
described in `.env.example` unless a fake adapter is injected in tests.

For memory-only use outside Docker, leave `FINARY_SESSION_PATH` absent or empty.
After `authenticate()` establishes renewable state, the same adapter renews
tokens without another password/MFA sign-in and creates no session or lock files.
Exiting or reloading the process loses that state. The operator-only
`bootstrap_session()` command requires configured storage to publish a session
for other processes; it cannot seed another process's memory.

## Required local checks

Run normal tests and static analysis from `finary-bridge`:

```bash
python -m pytest -m "not live" --ignore=tests/live
ruff check app tests
mypy app
```

Run repository contracts from the repository root:

```bash
python scripts/validate-json.py
python scripts/build-workflow-validation.py --check
COMPOSE_ENV_FILES=/dev/null docker compose config --quiet
COMPOSE_ENV_FILES=/dev/null bash scripts/validate-n8n-imports.sh
FINARY_REQUIRE_N8N_RUNTIME=1 python -m pytest -q \
  -n auto --maxprocesses 4 --dist worksteal --max-worker-restart 0 --durations=15 \
  finary-bridge/tests/test_n8n_zero_position_runtime.py \
  finary-bridge/tests/test_restore_run_identity_runtime.py
```

The n8n validator imports both workflow exports into an isolated ephemeral n8n
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

The required runtime gate uses CPU-detected `pytest-xdist` worker processes,
capped at four, on the same runner after the image has been pulled and both
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

## Workflow validation maintenance

The shared [validation source](../n8n/validation.js) is embedded in both workflow
exports by [build-workflow-validation.py](../scripts/build-workflow-validation.py).
The build reads `PortfolioSnapshotV2.model_json_schema()` and the verified empty
metadata default factories; it does not maintain another API field list. Its
small schema interpreter supports only the vocabulary used by these models.
Source-field constraints are also reused for the workbook columns that reference
those fields, alongside the fetched canonical workbook schema. The export is
self-contained and requires no additional n8n package or runtime endpoint.

After changing models or shared validation, run from the repository root with
the bridge development environment active:

```bash
python scripts/build-workflow-validation.py
python scripts/build-workflow-validation.py --check
python -m pytest -q finary-bridge/tests/test_prewrite_validation.py
```

Contract-parity tests compare every embedded copy with the generated source and
the model/workbook enums. The field matrix uses Pydantic as an independent input
oracle and executes the exported JavaScript. Separate output mutations exercise
every column, including missing keys and JavaScript `undefined` before JSON
serialization, batch structure, enum/date/number rules, and retained-row decoding.
Legacy workbook fixture IDs remain valid as read data; newly prepared fixture
runs now use realistic execution identities and timing origins. Import tests,
individual Code-node execution, workbook simulation and real n8n engine execution
are complementary evidence, not interchangeable checks.

## Test design

The normal suite is deterministic and credential-free:

- adapter tests use fake HTTP sessions and application-level exception checks;
- normalization tests use synthetic anonymized fixtures;
- API tests inject fake `FinaryClient` implementations;
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

## Opt-in live Finary checks

Live tests are excluded from CI and skipped unless their explicit opt-in flag is
set. Load credentials from a mode-restricted untracked file; never place them in
the command line or test output.

Adapter/entity smoke test:

```bash
cd finary-bridge
source .venv/bin/activate
set -a
source ../.env.live
set +a
unset FINARY_MFA_CODE
FINARY_LIVE_TEST=1 python -m pytest \
  -m live tests/live/test_finary_live.py -vv -s --tb=no
```

The test prompts for a one-time factor and reports structural assertions only.

Protected session lifecycle test:

```bash
SESSION_DIR="$(mktemp -d /private/tmp/finary-session-test.XXXXXX)"
(
  set -a
  source ../.env.live
  set +a
  unset FINARY_MFA_CODE
  export FINARY_SESSION_PATH="$SESSION_DIR/session.json"
  FINARY_LIVE_SESSION_TEST=1 python -m pytest \
    -m live tests/live/test_finary_session_live.py -vv -s --tb=no
)
stat -f 'session permissions: %Sp' "$SESSION_DIR/session.json"
```

Use a new empty temporary path on each run. Delete the temporary directory after
the check. Never point the test at a production session file or commit the
result.

Live output must not print account names, balances, positions, cookies, tokens,
or authentication payloads. A live check is evidence about the current private
API only; update code and anonymized fixtures together when its structure has
genuinely changed.

## Continuous integration

`.github/workflows/ci.yml` runs on pull requests and pushes to `main` with
read-only repository permissions. It has five bounded jobs:

| Job | Checks |
| --- | --- |
| `tests` | Python 3.12 normal pytest suite, explicitly excluding live tests |
| `session-validation-python314` | Python 3.14 session validation, including real JSON and injected decoder failures |
| `static-analysis` | Ruff and strict mypy for `app` |
| `repository-contracts` | JSON parsing and resolved Compose validation |
| `n8n-import` | isolated imports and required synthetic workflow executions using pinned n8n |

Actions are pinned to immutable revisions, runtime versions are explicit, and
the workflow does not read repository secrets, start the live stack, upload
portfolio artifacts, or publish n8n workflows. A green CI run validates the
repository artifacts; it does not prove that external credentials, Finary, or
Google Sheets are available.

## Change checklist

Before submitting a change:

1. keep Finary-specific behavior inside the adapter;
2. preserve `/v2/snapshot` schema `2.0` and workbook schema `2.1` unless the
   change explicitly coordinates a versioned contract revision;
3. update `docs/google-sheets-schema.json`, workflows, tests, and documentation
   together for a workbook contract change;
4. keep workflow exports credential-free and inactive;
5. run all checks relevant to the change;
6. inspect `git diff` and `git status`;
7. search changed files for secrets, personal financial data, raw payloads, and
   broken documentation links.

Do not weaken coverage, currency, null, identity, or idempotency rules to make a
test pass.
