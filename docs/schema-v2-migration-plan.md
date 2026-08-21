# Schema 2.0 liability-coverage migration plan

## Decision and objective

The Phase 9 live organization-scoped investigation could not prove complete
liability coverage. Schema `1.0` must therefore remain unchanged and fail-safe.
The recommended next implementation is a coordinated schema `2.0` migration
that makes liability coverage explicit while allowing truthful asset
synchronization.

This document is a migration specification, not an implementation. No `/v2`
route, workbook column, n8n behavior, or production schedule is changed yet.

## Bridge API

Add `GET /v2/snapshot` and preserve `GET /v1/snapshot` exactly. The new response
adds a required coverage object and makes liability-dependent totals nullable:

```json
{
  "schema_version": "2.0",
  "coverage": {"liabilities": "UNAVAILABLE"},
  "generated_at": "2026-08-21T07:30:12+02:00",
  "reference_currency": "EUR",
  "gross_assets_eur": 1000.0,
  "liabilities_eur": null,
  "net_worth_eur": null,
  "accounts": [],
  "positions": [],
  "liabilities": []
}
```

Allowed coverage states:

- `COMPLETE`: the liability collection is authoritative; empty means known
  zero; `liabilities_eur` and `net_worth_eur` are finite numbers.
- `PARTIAL`: individually verified liability records may be returned, but the
  authoritative total is unknown; both totals are null.
- `UNAVAILABLE`: no authoritative liability records or total is claimed; both
  totals are null.

Model validation must enforce those relationships. `gross_assets_eur` remains
the authoritative account-balance total. Position values are never added to it.

## Adapter and normalizer

Keep `FinaryLiabilityCoverage` and `FinaryRawLiabilities` inside the adapter
boundary. The organization and membership identifiers remain private. The
adapter may return `COMPLETE` only when runtime evidence satisfies the complete
scope, identity, value, EUR, lifecycle, deduplication, pagination, and
known-empty rules documented in the liability investigation.

Until a non-empty record schema is verified, the current live adapter should
return `UNAVAILABLE` with no records. A future `PARTIAL` reader may expose only
records whose individual semantics are verified. It must not claim an
authoritative sum. Normalization must keep metadata allowlisted and must not
copy raw organization, membership, institution, account, or linked-asset
objects.

## Google Sheets schema

Create a versioned `2.0` canonical Sheets definition rather than silently
editing the `1.0` file. The minimum new explicit columns are:

- `portfolio_daily.liability_coverage` (`ENUM`, non-null);
- `sync_runs.liability_coverage` (`ENUM`, nullable for failures before a
  snapshot is decoded).

Add the `COMPLETE`, `PARTIAL`, and `UNAVAILABLE` enum. Keep
`liabilities_eur` and `net_worth_eur` nullable. Blank numeric cells continue to
mean unknown, never zero; the coverage column explains why they are blank.

`liabilities_current` is changed only by a `COMPLETE` snapshot. In the initial
2.0 migration, `PARTIAL` and `UNAVAILABLE` must neither write partial current
rows nor mark an existing liability inactive. This deliberately preserves the
last known complete liability state. Storing partial rows later would require a
separate row-level provenance field and coexistence design.

## n8n synchronization

Add a version-aware validation branch for schema `2.0`:

- allow a successful asset snapshot for all three liability coverage states;
- synchronize accounts, positions, position history, and the daily gross-asset
  and allocation fields after normal validation;
- copy `liability_coverage` explicitly into daily and telemetry rows;
- write or inactivate `liabilities_current` only for `COMPLETE`;
- require numeric liability and net-worth totals only for `COMPLETE`;
- require null liability and net-worth totals for `PARTIAL` and `UNAVAILABLE`;
- emit `SUCCESS_WITH_WARNINGS` when asset synchronization succeeds without
  complete liability coverage;
- retain all existing pre-write validation, deterministic keys, manual-sheet
  ownership, retry, timeout, and partial-write recovery behavior.

No incomplete snapshot may be represented as a complete net-worth snapshot.

## Telemetry and ChatGPT semantics

`sync_runs.liability_coverage` records the decoded coverage independently of
run status. Operational failures before decoding leave it blank. A successful
asset-only run with incomplete liabilities is not a Finary feature error; it is
`SUCCESS_WITH_WARNINGS` with explicit coverage.

Workbook documentation and ChatGPT instructions must state:

- gross assets and asset allocation may be analyzed under any coverage state;
- `PARTIAL` records, if later supported, are not the complete debt set;
- net worth must never be stated or inferred unless coverage is `COMPLETE`;
- blank liability/net-worth cells are unknown, not zero;
- last-known complete liability rows must not be described as current after an
  incomplete snapshot without an explicit freshness warning.

## Compatibility and migration order

1. Add strict v2 Pydantic models and deterministic bridge tests while retaining
   every v1 test.
2. Add `/v2/snapshot`; keep `/v1/snapshot` unchanged.
3. Add a versioned `2.0` Sheets schema and schema-drift tests.
4. Migrate a protected workbook copy by adding the two coverage columns; do not
   rewrite historical blank totals as zero.
5. Update a copied, inactive n8n workflow and its executable regression tests.
6. Run fixture acceptance for `COMPLETE`, `PARTIAL`, and `UNAVAILABLE`, including
   liability lifecycle protection.
7. Run one inactive live v2 synchronization and inspect only sanitized
   structural outcomes.
8. Promote the workbook and workflow only after backup and rollback checks.

Rollback keeps v1 and the existing inactive workflow available. Production
scheduling remains a separate later gate.

## Required test matrix

- coverage/total model invariants for all three states;
- v1 compatibility and unchanged fail-safe behavior;
- v2 HTTP success with incomplete coverage and null totals;
- COMPLETE empty known-zero behavior;
- PARTIAL/UNAVAILABLE cannot inactivate liability rows;
- assets and history remain idempotent under incomplete coverage;
- coverage columns survive same-day upsert and telemetry writes;
- ChatGPT-facing data dictionary forbids net-worth inference;
- schema, n8n, operational, secret, and private-data regressions.

## Revised Phase 9 acceptance after migration

After schema `2.0` is separately approved and implemented, Phase 9 may accept a
live HTTP 200 with `PARTIAL` or `UNAVAILABLE` liability coverage when the state
is explicit, liability and net-worth totals are null, asset synchronization is
correct, and incomplete data cannot alter last-known complete liabilities.
Those criteria do not apply to schema `1.0`.
