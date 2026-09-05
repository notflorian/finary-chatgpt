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
docker compose config --quiet
bash scripts/validate-n8n-imports.sh
```

The n8n validator imports both workflow exports into an isolated ephemeral n8n
instance with no network and no persistent project volumes. Docker must already
have the image pinned by `docker-compose.yml`.

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
read-only repository permissions. It has four bounded jobs:

| Job | Checks |
| --- | --- |
| `tests` | Python 3.12 normal pytest suite, explicitly excluding live tests |
| `static-analysis` | Ruff and strict mypy for `app` |
| `repository-contracts` | JSON parsing and resolved Compose validation |
| `n8n-import` | network-isolated import of both workflow exports using pinned n8n |

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
