# Continuous integration

## Scope

GitHub Actions runs the credential-free `CI` workflow on every pull request and
every push to `main`. It uses GitHub-hosted Ubuntu runners and read-only
`contents` permission. It has no scheduled trigger, `pull_request_target`,
deployment access, artifact upload, dependency cache, or production secret.

The stable check names are:

- `tests`
- `static-analysis`
- `repository-contracts`
- `n8n-import`

After the workflow has been published and observed successfully, all four names
should become required pull-request checks before production activation. Phase
11 does not change repository branch protection itself.

## Runtime and action pins

Python is pinned to `3.12.14` and Node.js to the `22.23.2` LTS patch release.
Node is installed explicitly so executable n8n Code-node tests cannot silently
skip because the runner lacks `node`.

Every GitHub Action reference uses a reviewed full commit SHA:

- `actions/checkout` `v7.0.1`;
- `actions/setup-python` `v7.0.0`;
- `actions/setup-node` `v7.0.0`.

Checkout disables persisted Git credentials. No third-party action, cache, or
artifact action is used.

## Gate responsibilities

### `tests`

Installs `finary-bridge` with its existing `.[dev]` dependency contract and
runs:

```bash
cd finary-bridge
python -m pytest -m "not live" --ignore=tests/live
```

Both the marker and path exclusion are intentional independent defenses. CI
does not set a live-test flag or provide a Finary, Clerk, Google, workbook, or
production n8n credential. Pytest retains `-ra` from `pyproject.toml`, making
unexpected skip reasons visible.

### `static-analysis`

Runs Ruff and mypy as separate steps so the failing tool is immediately clear:

```bash
cd finary-bridge
python -m ruff check .
python -m mypy app
```

### `repository-contracts`

Parses the canonical schema and both workflow exports using only Python's
standard library, then validates Compose without printing expanded
configuration:

```bash
python scripts/validate-json.py
docker compose config --quiet
```

The normal pytest suite supplies the deeper schema, workflow, Compose topology,
session-store, and operational regression checks.

### `n8n-import`

Runs:

```bash
bash scripts/validate-n8n-imports.sh
```

The script derives exactly one `n8nio/n8n` image from
`docker compose config --images`, requires version `2.35.5` with a digest, and
pulls that exact reference. Each canonical workflow is then imported
individually into a fresh ephemeral container with:

- `--network none` and `--pull never` after the explicit image pull;
- a container-local temporary n8n user directory;
- a clearly synthetic CI-only encryption key;
- diagnostics and personalization disabled; and
- only the workflow under test mounted read-only.

The validator never mounts `n8n_data`, `finary_session_data`, `.env`, a user
home directory, or the repository as a whole. Import does not execute, publish,
or activate either workflow, and the container state disappears on exit.

## Security boundary

Normal CI never connects to Finary, Clerk, Google Sheets, the canonical
workbook, the live n8n instance, or the live Docker host. It runs only on
GitHub-hosted runners and references no `secrets.*` value. Do not add production
credentials, a GitHub Environment, a self-hosted runner, live-test opt-in flags,
or `docker compose up` to this workflow.

The synthetic n8n import key exists only inside disposable import containers.
It is not suitable for live state and must never replace the production
`N8N_ENCRYPTION_KEY`.

## Diagnosing failures

- `tests`: inspect the named pytest failure or unexpected skip reason. Node-
  backed tests must execute under the pinned Node runtime.
- `static-analysis`: run the failing Ruff or mypy command independently.
- `repository-contracts`: validate the named JSON file, then run Compose with
  `--quiet`; do not print expanded configuration in shared logs.
- `n8n-import`: reproduce with the validator. A failure means either Compose no
  longer resolves one digest-pinned n8n 2.35.5 image or the real pinned CLI
  rejected a canonical workflow.

Do not bypass or weaken a gate to activate synchronization. Phase 12 activated
the protected live schedule only after all four exact-main checks were green
and the user explicitly approved publication. The current private-repository
plan did not permit configuring or verifying required-check enforcement, so CI
status was inspected directly and no unsupported enforcement claim is made.

## Live diagnostics

Live Finary and persisted-session tests remain manual, local, and explicitly
opt-in as documented in `README.md` and `operations.md`. Phase 11 deliberately
adds no live-test workflow and no Google synchronization test.

**PRODUCTION SCHEDULE IS ACTIVE; FIRST NATURAL RUN PASSED ACCEPTANCE.**
