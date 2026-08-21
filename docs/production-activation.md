# Phase 12 production activation record

## Result

`Finary - Daily Sync` was published in the protected local n8n runtime on
2026-08-22 after explicit user approval. The schedule is `30 7 * * *` in
`Europe/Paris`; the first natural scheduled execution is pending. The
repository export remains inactive so imports cannot start a schedule.

## Activated revision and gates

- exact `main` revision: `1bc9206dcfd139583730beee8f4ccc65028b2805`;
- dependency issues #15, #16, and #17 were closed;
- exact-revision `tests`, `static-analysis`, `repository-contracts`, and
  `n8n-import` checks were green;
- required-check enforcement could not be configured or verified on the
  current private-repository plan; no enforcement claim is made;
- schema version `2.0` and explicit liability coverage semantics were retained.

## Pre-activation safety evidence

- all Compose services were healthy and isolated on the expected local network;
- n8n reached the bridge and private canonical-schema service;
- the live workflow matched the repository workflow structurally while
  preserving runtime-only credentials, IDs, ownership, and error linkage;
- every Sheets node had a credential, bounded retries and timeouts were intact,
  reads executed once, and writes processed all prepared rows;
- a fresh owner-only n8n-volume checkpoint and verified SHA-256 sidecar existed;
- the matching n8n encryption key was preserved separately;
- a private canonical-workbook copy retained the ten exact schema-2.0 tabs;
- bridge session state was deliberately excluded from backup.

## Final inactive manual preflight

One final editor-initiated execution completed successfully before publication.
It recorded `SUCCESS_WITH_WARNINGS`, schema `2.0`, explicit `UNAVAILABLE`
liability coverage, and only the expected `LIABILITY_COVERAGE_UNAVAILABLE` and
`PARTIAL_POSITION_EUR_COVERAGE` warnings. Liability-dependent totals remained
blank, manual sheets were unchanged, deterministic keys remained unique, and
the liability sheet was not modified. No private values or identifiers are
recorded here.

## Activation and monitoring

Publication did not trigger an extra execution. Exactly one active daily
schedule targets `/v2/snapshot`; the error handler remains linked and has no
schedule. Accept the first natural 07:30 run only if it produces `SUCCESS` or
understood `SUCCESS_WITH_WARNINGS`, preserves schema/coverage/null semantics,
advances one telemetry row, retains deterministic keys, and leaves manual
sheets unchanged.

If that run fails or an unattended run becomes unsafe, immediately unpublish
the daily workflow using the n8n UI or the supported `unpublish:workflow`
command documented in `operations.md`. Do not delete workflows, volumes,
history, workbook data, or the error handler. Treat the synchronization as
stale after more than 48 hours without a successful terminal run while the host
is expected to be online.

Issue #18 remains open until the first natural scheduled execution is accepted.
Do not start issue #19 before that acceptance.
