# Phase 10 Compose migration acceptance

Issue #16 was formally accepted locally on 2026-08-22. The live bridge,
canonical schema service, and n8n instance now run from the repository
`docker-compose.yml` as one Compose project. Acceptance requires repository and
GitHub artifacts to remain free of credentials and private financial data; no
such data is present in the repository or this document.

## Accepted topology

| Service | Exposure | Persistent state | Network |
| --- | --- | --- | --- |
| `finary-bridge` | `127.0.0.1:8000` | `finary_session_data` only | `finary-stack` |
| `n8n` | `127.0.0.1:5678` | `n8n_data` only | `finary-stack` |
| `schema-server` | no host port | read-only canonical JSON bind | `finary-stack` |

The migrated n8n state retained the owner account, encrypted Google Sheets
credential, both canonical workflows, workflow linkage, and execution history.
The daily workflow remained inactive. The error handler remained published so
it can be selected as the daily workflow's error workflow; it has no schedule
or public trigger.

The accepted legacy n8n runtime explicitly allowed workflow expressions to read
environment variables. The repository Compose service preserves that required
setting because the canonical workflow resolves its local service URLs,
workbook identifier, and optional bridge key through `$env`. The n8n editor
must therefore remain local and access-controlled.

Live pre-write smoke validation also showed that the renamed legacy workflows
still contained obsolete v2-only parameters. The live records were reconciled
to the repository exports by node name while preserving their existing IDs,
project ownership, Google credential bindings, and error-workflow linkage.
Both schema requests use Text response mode, and their Code nodes accept the
n8n 2.35.5 full-response payload under `data` as well as the test-compatible
`body`/decoded-object forms.

The bridge session store remained a separate bridge-only volume. Its directory
and state file retained owner-only permissions. The schema server serves
`docs/google-sheets-schema.json` inside the Compose network and has no public
port.

## Backup and restore evidence

Before changing n8n storage, the legacy n8n container was stopped cleanly. A
full archive of its data volume, a SHA-256 sidecar, and workflow exports were
placed outside the repository in an owner-only directory on a FileVault-
protected local volume. The checksum was verified before restore.

The archive was first restored into a temporary isolated Docker volume. An
isolated n8n instance started with the original encryption key and verified:

- the existing owner setup;
- decryptability of the Google Sheets credential;
- the canonical daily and error workflows; and
- retained execution telemetry.

Only after that restore test passed was the archive copied into the Compose-
managed `n8n_data` volume. The legacy source volume and protected backup were
retained as rollback sources during acceptance. The bearer-equivalent
`finary_session_data` volume was deliberately excluded from the backup.

## Live verification

The migrated stack passed these sanitized checks:

- all three Compose services reached their configured health checks;
- n8n reached the bridge and schema server by their internal service names;
- the canonical schema reported version `2.0`;
- the owner setup, decryptable Google credential, workflows, error linkage,
  inactive daily schedule, and prior execution history were present;
- two separated `/v2/snapshot` requests succeeded without another MFA prompt,
  including protected-session reuse across a refresh boundary;
- the live workbook retained all ten canonical sheets with exact schema-2.0
  headers;
- one inactive manual execution completed with `SUCCESS_WITH_WARNINGS`, explicit
  unavailable liability coverage, null dependent totals, unchanged same-day
  current/history/daily row counts, and no liability rows; and
- manual/owner-controlled sheet structure and row counts remained unchanged.

The snapshot checks validated only structure, coverage semantics, keys, and
cross-references. Repository documentation and committed evidence contain no
personal portfolio values.

## Lifecycle and rollback boundary

Routine lifecycle control is now exclusively:

```bash
docker compose build
docker compose up -d
docker compose down
```

Never add `-v` to `docker compose down` during routine operation. Rollback is a
controlled restore of the protected archive into an empty n8n volume while n8n
is stopped, using the matching encryption key. A restart or recreation of one
service must not delete another service's state because the n8n and Clerk
volumes are distinct.

Phase 10 itself did not add CI, enable the daily schedule, or connect ChatGPT.
Phase 11 CI is now implemented locally but still needs remote observation after
publication. Activation and ChatGPT access remain issues #18 and #19.

**PRODUCTION SCHEDULE REMAINS DISABLED.**
