# Finary Portfolio Data 1.1.0

A reliability and data-integrity release for the local Finary -> n8n -> Google
Sheets -> ChatGPT pipeline.

## Upgrade required for existing installations

Follow the [migration guide from 1.0.0 to 1.1.0](https://github.com/notflorian/finary-chatgpt/blob/v1.1.0/docs/migration-1.0-to-1.1.md)
before resuming synchronization. Rebuilding containers alone is not sufficient:
the workbook, both n8n workflows, credential bindings, and ChatGPT reference
need coordinated adoption during a maintenance window.

| Contract | 1.0.0 | 1.1.0 |
| --- | --- | --- |
| Bridge application | `1.0.0` | `1.1.0` |
| Canonical endpoint / API schema | `/v2/snapshot` / `2.0` | Unchanged |
| Workbook schema | `2.0` | `2.1`: nullable `positions_history.run_id` appended |
| Persisted session format | `1` | `1`: existing files remain readable; coordinated sidecar locking added |

Do not backfill historical run IDs, replace the n8n encryption key, delete
volumes, or resume executions saved with old workflow code. Valid existing
Finary session state can be reused after all old writers have stopped; MFA is
needed only if the session is unavailable or rejected, or a restore is performed.

## Highlights

- **Bridge authentication and renewal:** the optional bridge API key is enforced
  before snapshot client initialization. A process-scoped client, proactive
  token renewal, bounded recovery from entity HTTP 401 responses, coordinated
  session replacement, and memory-only renewal improve long-running operation.
  The Compose bridge now has a restart policy.
- **Malformed-input handling:** invalid session JSON, invalid format versions,
  deeply nested upstream responses, and oversized numeric values produce
  sanitized failures without leaking private data or weakening validation.
- **Complete, validated synchronization:** the workflow validates the snapshot
  and every prepared write batch before portfolio writes. Explicit collection
  completeness evidence allows a valid zero-position portfolio without dummy
  rows. Unknown optional values explicitly clear existing Sheets cells instead
  of silently retaining stale values.
- **Traceable workbook state:** history carries successful-run membership;
  current tables and historical fallback require independent key, count, and
  provenance checks. New run identities combine the n8n execution ID with a
  fresh UUID so a restored database cannot reuse old workbook identities.
  The error handler retrieves the original run through the local n8n API.
- **More reliable telemetry:** success completion time is finalized after
  portfolio writes, and net-worth comparison uses an unambiguous retained
  successful COMPLETE baseline. Valuation changes are not investment returns.
- **Reviewability and testing:** Code-node JavaScript is maintained in readable
  source files and embedded into generated, importable n8n JSON exports.
  Credential-free regressions cover producer/consumer contracts, Python 3.14
  decoding behavior, and the Compose-pinned n8n runtime. CI avoids repeated
  parallel image pulls and bounds runtime-test concurrency.

## Important limitations

- Finary's API remains private and unsupported; no new unverified liability or
  currency-conversion support is claimed. Incomplete liability coverage leaves
  debt and net-worth totals unknown, not zero.
- Sheets writes and reads are not transactional. Membership checks detect
  observed inconsistencies but cannot guarantee an atomic portfolio snapshot.
  Keep one writer and do not overlap manual and scheduled executions.
- Old history with blank membership remains retained but cannot prove a complete
  historical portfolio. A new successful run does not repair all old dates or
  values in rows it does not refresh.
- The executable workbook consumer is a test reference, not an automatically
  installed enforcement layer inside ChatGPT. Update the Project knowledge file
  and reading instructions explicitly.
- The stack remains local-first and single-user, with no trading, transaction
  ingestion, or investment-performance calculation.

[Full comparison with 1.0.0](https://github.com/notflorian/finary-chatgpt/compare/v1.0.0...v1.1.0)
