# Phase 9 end-to-end acceptance

## Result

Phase 9 was accepted on 2026-08-21 against the canonical schema `2.0`
contract. The accepted live path is:

```text
GET /v2/snapshot -> Finary - Daily Sync -> Finary Portfolio Data
```

The daily workflow remained unpublished and inactive throughout acceptance.
This result does not authorize production scheduling.

This document records structural outcomes only. It intentionally contains no
workbook identifier, upstream identifier, portfolio value, account or position
name, institution, authentication material, or raw provider response.

## Evidence classification

### Previously verified by issue #23

- protected schema-2.0 workbook migration and canonical artifact promotion;
- live HTTP 200 with explicit `UNAVAILABLE` liability coverage and null
  liability-dependent totals;
- same-day deterministic current, history, and daily keys;
- missing-position inactivation without deletion;
- protected manual-sheet ownership;
- successful asset synchronization under incomplete liability coverage;
- repeated in-process refresh after the 45-second refresh boundary.

### Rechecked live during issue #15

- `/health` returned HTTP 200 without authenticating to Finary;
- a bridge restart reused the protected Clerk session without a new MFA code;
- a later request beyond the refresh boundary also returned HTTP 200;
- `/v2/snapshot` returned schema `2.0`, explicit `UNAVAILABLE` coverage,
  nonempty account and position structures, unique category-aware identities,
  valid account references, and valid coverage/total relationships;
- all ten workbook sheets existed and their ordered headers matched
  `docs/google-sheets-schema.json`;
- one inactive Manual Trigger execution completed successfully and recorded
  `SUCCESS_WITH_WARNINGS` with schema `2.0` and `UNAVAILABLE` coverage;
- current, history, daily, and telemetry keys remained unique;
- active current rows carried the new run's last-seen context;
- known-EUR position weights used the known-EUR active-position denominator;
- the current date had one logical daily key and deterministic history keys;
- incomplete coverage left liability and net-worth totals blank and skipped the
  liability write path;
- ephemeral before/after fingerprints proved `README`, `allocation_targets`,
  `asset_overrides`, and `cashflows` were unchanged.

No manual MFA was required during the issue #15 restart or refresh checks. That
means the existing protected upstream session was still valid; it does not
remove the documented requirement for manual bootstrap after expiry or
revocation.

### Deterministic acceptance tests

Credential-free tests cover:

- schema-2.0 model and coverage/total invariants;
- `COMPLETE`, `PARTIAL`, and `UNAVAILABLE` workflow validation;
- exact category-aware identities, account references, and null handling;
- same-day idempotency and next-day history/daily keys;
- missing-position retention and inactivation under incomplete coverage;
- `COMPLETE` known-empty liability inactivation;
- `PARTIAL` and `UNAVAILABLE` preservation of last-known complete liabilities;
- suspicious empty and malformed snapshot rejection before writes;
- structured authentication and upstream failure safety;
- header drift, Google authentication, quota, temporary-service, and timeout
  failure classification with bounded retries;
- deterministic repair after a simulated mid-write failure, including under
  incomplete liability coverage;
- last-success semantics and sanitized error telemetry;
- session-store isolation, restrictive persistence, refresh, rejection, and
  secret-exclusion rules.

## Accepted semantics

Account balances remain the authoritative source of `gross_assets_eur`.
Position values are analytical components and are never added to account
balances. Position allocation uses only active positions with a known
`market_value_eur`; unknown values remain blank and are not converted to zero.

Only `COMPLETE` liability coverage may update or inactivate
`liabilities_current` and publish numeric liability/net-worth totals.
`PARTIAL` and `UNAVAILABLE` preserve last-known complete liability rows and
keep current liability/net-worth totals blank. Consumers must not present those
preserved rows as current authoritative liabilities when the latest daily
coverage is incomplete.

`SUCCESS_WITH_WARNINGS` is a successful asset synchronization and participates
in last-success selection. A later `FAILED` row cannot replace the newest valid
`SUCCESS` or `SUCCESS_WITH_WARNINGS` completion.

## Security result

The protected session volume was observed only on `finary-bridge`; it was not
mounted into n8n or the schema server. Repository tests and scans found no live
credentials, session values, workbook identifier, personal identifiers, or
portfolio values. The live checks emitted structural status labels only.

## Remaining production gates

Phase 9 acceptance satisfies the implementation scope of issue #15. The
remaining roadmap is:

1. #16 — repository Compose migration accepted; see `compose-migration.md`;
2. #17 — CI quality gates implemented; all four GitHub-hosted checks observed
   green;
3. #18 — activate production synchronization safely after green CI;
4. #19 — connect ChatGPT to the validated workbook.

**PRODUCTION SCHEDULE REMAINS DISABLED.**
