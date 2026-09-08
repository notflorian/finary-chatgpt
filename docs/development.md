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
FINARY_REQUIRE_N8N_RUNTIME=1 python -m pytest -q -n auto --maxprocesses 4 --dist worksteal --max-worker-restart 0 --durations=15 \
  finary-bridge/tests/test_n8n_zero_position_runtime.py \
  finary-bridge/tests/test_restore_run_identity_runtime.py \
  finary-bridge/tests/test_sheets_connector_runtime.py
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

The connector regression loads the installed `appendOrUpdate.execute` and
`GoogleSheet` implementation from that same Compose-pinned image. It executes
the exported preparation and finalization code with synthetic snapshots, then
applies the actual connector's emitted updates to individual in-memory cells.
Only Sheets I/O is replaced; update preparation, column addressing, exported
mapping expressions and append conversion remain real. A network-disabled Node
process is reused within each test worker; no n8n server, database, credentials
or project volumes are needed. This required gate covers all eight write paths,
known/null transitions, same-day history, retries, zero/false preservation and
consumer acceptance. The `test_verified_scpi_crypto_null_known_null_clears_actual_cells`
case starts with adapter-owned fixtures, constructs real snapshots, and verifies
SCPI/crypto null → known → null transitions through the exported JavaScript and
installed connector, including retained costs and prior-day history. Its
null-versus-empty-string countercheck demonstrates why
auto-mapped null retains an old cell even with `allowEmptyValues=true`.

When `pytest-xdist` runs with `-n auto`, worker count comes from
`tests/conftest.py`: local runs default to `2`, while CI scales to available CPU
capacity (capped at `4`). Set `PYTEST_XDIST_WORKER_COUNT=<N>` to force an exact
worker count in both local and CI environments.
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

Code-node logic lives in checked-in sources under `n8n/code-nodes/`, grouped by
workflow export stem and a lowercase hyphenated node name. For example,
`n8n/code-nodes/finary-daily-sync/prepare-validated-rows.js` is the source of
the **Prepare Validated Rows** Code node in
`n8n/workflows/finary-daily-sync.json`.

Edit those `.js` files directly, then regenerate the portable workflow exports:

```bash
python scripts/build-workflow-validation.py
python scripts/build-workflow-validation.py --check
```

The build rewrites every `parameters.jsCode` field from the checked-in source
files and prepends the generated contract block only for the nodes that use the
shared validation helpers. The workflow JSON remains the self-contained import
artifact for the pinned n8n version; n8n never reads repository files at
runtime.

The build also embeds [sheets-serialization.js](../n8n/sheets-serialization.js)
only in the eight Code nodes immediately before Sheets upserts. This separate
prelude is necessary because ordinary row selectors do not receive the contract
validation prelude. Contract validation and the all-batch portfolio gate run
before serialization. Internal nullable values remain null; outgoing null cells
become explicit empty strings, with absent/undefined fields and required blanks
rejected at the boundary. Edit this shared source and the readable Code nodes,
then regenerate both exports with the same build command.

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
| `session-validation-python314` | Python 3.14 session and upstream-response validation, including real payloads and injected decoder/copy failures |
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

## Publishing 1.1.0

Release preparation is separate from upgrading an operator's running stack.
Review and merge the release PR through the normal protected workflow. Require
all five CI jobs to succeed on the exact merged commit: `tests`,
`session-validation-python314`, `static-analysis`, `repository-contracts`, and
`n8n-import`. An earlier green run is not evidence for a later commit, and CI
does not validate a production workbook or live credentials.

From a clean maintainer checkout with normal GitHub write access:

```bash
git fetch origin main --tags
git status --short
git rev-parse origin/main
git tag --list v1.1.0
```

Stop if local changes would be overwritten or if the tag/release already exists;
inspect it rather than moving a tag or publishing a duplicate. Select the full
merged commit SHA that passed the five jobs, check out that exact commit, and
verify `app/config.py`, `pyproject.toml`, `/health` expectations, release notes,
and the migration guide all describe `1.1.0`. Do not tag the pre-merge PR head or
silently select a newer unvalidated `main`.

Once that exact commit is checked out and approved for publication:

```bash
git tag -a v1.1.0 -m "Finary Portfolio Data 1.1.0" HEAD
git push origin refs/tags/v1.1.0
gh release create v1.1.0 \
  --repo notflorian/finary-chatgpt \
  --verify-tag \
  --title "Finary Portfolio Data 1.1.0" \
  --notes-file docs/release-1.1.0.md \
  --latest
```

Stop at any rejected operation; do not bypass tag rules or branch protections.
`--verify-tag` requires the tag to exist remotely instead of implicitly creating
one on a potentially different commit. The notes file is the reviewed release
body, including the tag-pinned migration link. See the
[GitHub CLI release documentation](https://cli.github.com/manual/gh_release_create).

Verify the published release title, tag commit, source archives, rendered notes,
and migration link. Do not attach `.env`, credential-bearing workflow exports,
session state, workbook backups, or real portfolio data. Operators can then
follow the [migration runbook](migration-1.0-to-1.1.md); publishing the release
does not deploy it or migrate any installation.
