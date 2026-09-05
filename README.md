# Finary Portfolio Data

Finary Portfolio Data is a local-first pipeline that turns a private Finary
portfolio into a stable Google Sheets data model that ChatGPT can analyze.

```text
Finary -> finary-bridge -> n8n -> Google Sheets -> ChatGPT
```

The bridge owns Finary authentication and private-API parsing. n8n consumes the
normalized `/v2/snapshot` API and synchronizes deterministic current-state,
history, and telemetry tables. Neither Google Sheets nor ChatGPT receives
Finary credentials or raw upstream payloads.

## Requirements

- Docker Engine with Docker Compose v2
- a Finary account and access to its current MFA method
- a Google account that can create a spreadsheet and an OAuth credential in n8n
- a ChatGPT account with Projects and Google Drive sources, if you want the
  ChatGPT integration
- `git` and `jq`; Python 3.12+ is needed only for local development

## Quick start

### 1. Configure the local stack

```bash
git clone https://github.com/notflorian/finary-chatgpt.git
cd finary-chatgpt
cp .env.example .env
chmod 600 .env
```

Edit `.env` and set at least:

```dotenv
FINARY_EMAIL=you@example.com
FINARY_PASSWORD=
FINARY_GOOGLE_SHEET_ID=
N8N_ENCRYPTION_KEY=
```

Use a strong, stable `N8N_ENCRYPTION_KEY`; losing or changing it prevents n8n
from decrypting stored credentials. Do not store a TOTP secret or backup code in
this file. `.env` is ignored by Git, but verify that before entering secrets.

Start the stack:

```bash
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8000/health
```

Expected health response:

```json
{"status":"ok","service":"finary-bridge","version":"1.0.0"}
```

The bridge and n8n listen only on `127.0.0.1` by default. The canonical Sheets
schema `2.1` is served only on the internal Compose network.

### 2. Create the workbook

Create one Google spreadsheet named **Finary Portfolio Data** with these tabs in
this order:

```text
README
accounts_current
positions_current
liabilities_current
positions_history
portfolio_daily
allocation_targets
asset_overrides
cashflows
sync_runs
```

Copy its spreadsheet ID into `FINARY_GOOGLE_SHEET_ID`, then restart n8n:

```bash
docker compose up -d --force-recreate n8n
```

For every tab, copy the ordered headers from
[`docs/google-sheets-schema.json`](docs/google-sheets-schema.json). For example:

```bash
SHEET=accounts_current
jq -r --arg sheet "$SHEET" '.sheets[$sheet].columns | map(.name) | @tsv' \
  docs/google-sheets-schema.json
```

Paste the output into row 1. Populate the `README` tab from the JSON
`readme_entries` array. The workbook rules and ownership boundaries are
summarized in [the data-model guide](docs/data-model.md).

### 3. Configure n8n

Open [http://127.0.0.1:5678](http://127.0.0.1:5678), complete the local owner
setup, and create a Google Sheets OAuth2 credential with access to the workbook.

Import both repository exports:

- `n8n/workflows/finary-error-handler.json`
- `n8n/workflows/finary-daily-sync.json`

Assign the Google credential to **every** Google Sheets node in both workflows.
Publish the error handler, then select it as the daily workflow's error
workflow. Keep the daily workflow unpublished until its manual run passes.

### 4. Bootstrap the Finary session

The HTTP API never prompts for MFA. Bootstrap the bridge's protected session in
an interactive terminal after the stack starts:

```bash
docker compose exec -e FINARY_MFA_CODE= finary-bridge python -c '
import getpass
from app.finary_client import FinaryApiClient

client = FinaryApiClient.from_environment(
    second_factor_code_provider=lambda strategy: getpass.getpass(
        f"Enter the one-time Finary {strategy} code: "
    )
)
client.authenticate()
client.get_accounts()
print("Persisted session bootstrap passed")
'
```

The bridge stores only the minimum Clerk restart state in a private Docker
volume. It does not persist passwords, TOTP secrets, backup codes, or bearer
JWTs. Repeat the bootstrap after session expiry, revocation, credential change,
or loss of the session volume.

### 5. Run and verify the first synchronization

Click **Execute workflow** in **Finary - Daily Sync**. Confirm that:

- the execution reaches `Record Successful Sync`;
- `sync_runs` ends with `SUCCESS` or `SUCCESS_WITH_WARNINGS`;
- `accounts_current` and `positions_current` contain deterministic unique keys;
- rerunning on the same day creates no duplicate current, history, or daily
  rows;
- `positions_history` rows for the successful `run_id` equal
  `sync_runs.positions_count` and match `portfolio_daily.run_id`;
- manual tabs remain unchanged.

Warnings are meaningful. In particular, `UNAVAILABLE` liability coverage means
liabilities and net worth are unknown, not zero. Publish the daily workflow only
after the checks pass. It runs at 07:30 in `Europe/Paris`.

See [Operations](docs/operations.md) for recovery, rotation, backup, and
schedule controls.

## ChatGPT

Use a private ChatGPT Project. Add the workbook as a Google Drive source and
upload these repository references:

- your personal investment policy;
- [`docs/finary-portfolio-data-knowledge.md`](docs/finary-portfolio-data-knowledge.md).

The complete setup and safe interpretation rules are in
[ChatGPT integration](docs/chatgpt.md).

## API

- `GET /health` reports service health without contacting Finary.
- `GET /v2/snapshot` is the canonical normalized contract, schema `2.0`.
- `GET /v1/snapshot` remains available as a strict legacy contract. It requires
  complete liability coverage and therefore fails safely when that coverage is
  unavailable.

If `FINARY_BRIDGE_API_KEY` is configured, snapshot requests must send it in the
`X-API-Key` header. Responses never contain private upstream objects.

## Development

```bash
cd finary-bridge
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -m "not live" --ignore=tests/live
python -m ruff check .
python -m mypy app
cd ..
python scripts/validate-json.py
docker compose config --quiet
bash scripts/validate-n8n-imports.sh
```

Live Finary tests are opt-in and require private credentials. See
[Development](docs/development.md).

## Documentation

| Document | Purpose |
| --- | --- |
| [Architecture](docs/architecture.md) | Components, trust boundaries, API contracts, authentication, and versioning |
| [Data model](docs/data-model.md) | Workbook semantics, keys, nulls, ownership, and update rules |
| [Operations](docs/operations.md) | Installation follow-through, recovery, rotation, backup, and monitoring |
| [ChatGPT integration](docs/chatgpt.md) | Private Project setup and safe workbook interpretation |
| [Development](docs/development.md) | Local checks, CI, fixtures, and opt-in live tests |
| [ChatGPT knowledge reference](docs/finary-portfolio-data-knowledge.md) | Reference file uploaded to the ChatGPT Project |
| [Canonical schema](docs/google-sheets-schema.json) | Machine-readable workbook contract |

## Security and limitations

- This project uses Finary's private, unsupported API. Upstream changes may
  require adapter updates.
- The bridge is local-only by default; do not expose it or n8n publicly without
  adding an appropriate security boundary.
- Finary credentials and session state belong only to the bridge. Google OAuth
  credentials belong only to n8n.
- Liability coverage may be `PARTIAL` or `UNAVAILABLE`; blank liability and net
  worth cells must never be interpreted as zero.
- Position values can have partial verified-EUR coverage. Gross assets use
  authoritative account balances and must not be recomputed by adding position
  values.

## License

This project is available under the [MIT License](LICENSE).
