# Liability coverage investigation

## Phase 9 live organization-scoped verification

On 2026-08-21, Phase 9 closed the live-call evidence gap left by Phase 7. The
probe reused the protected Phase 8 Clerk session and called only the
source-evidenced read surfaces:

- `GET /users/me/organizations`;
- `GET /organizations/{organization_id}/memberships/{membership_id}/portfolio?new_format=true&period=all`;
- `GET /organizations/{organization_id}/memberships/{membership_id}/portfolio/credits/accounts?period=all`.

The identifiers remained in memory and were never printed or stored. The
portfolio and credits calls were made for every discovered membership so that
an owner-only selection could not silently omit a separate profile.

Sanitized structural findings:

| Question | Live finding | Completeness consequence |
| --- | --- | --- |
| Authentication | The protected Clerk session refreshed and authenticated without a new factor. | Phase 8 restart reuse remains verified. |
| Context discovery | The organizations result was a non-empty list with stable organization and membership IDs. Exactly one owner context was discoverable, and multiple memberships existed. | A single owner context is not automatically portfolio-wide across every accessible profile. Aggregation and shared-liability rules remain necessary. |
| Portfolio overview | Callable for every discovered membership. The result was an object with `gross`, `net`, and `finary` sections, nested `total`, `assets`, and `liabilities` objects, plus `has_unqualified_loans` and `has_unlinked_loans`. | The flag names are UI-status evidence, not a documented completeness guarantee. |
| Credits accounts | Callable for every discovered membership and returned a list in the standard envelope. Every list was `EMPTY`. | No representative liability record exists from which to verify identity, balance, currency, lifecycle, category, ownership, or linked-loan semantics. |
| Reconciliation | For every membership, `gross.total.amount - net.total.amount` matched both the empty credits sum and the zero debt implied by the observed overview, within an absolute EUR tolerance of `0.01`. | This supports that the current displayed contexts contain no recognized debt, but does not prove that an empty credits list is an authoritative complete-zero contract. |
| Pagination | No pagination fields or link header were present on the observed overview or credits responses. | An empty single response cannot prove that the endpoint is intrinsically unpaginated or complete for a non-empty portfolio. |
| Duplication | No cross-membership credit ID collision was observable because every collection was empty. | Deduplication semantics remain unverified. |

The probe printed field names, JSON types, `EMPTY`/`NON_EMPTY`, and
`MATCH`/`NO_MATCH` statuses only. It did not print or persist identifiers,
names, institutions, addresses, amounts, raw JSON, authentication material, or
portfolio values.

### Phase 9 completeness matrix

| Requirement | Result |
| --- | --- |
| Callable live source | Proven |
| Portfolio-wide relevant scope | Not proven across multiple memberships |
| Manual and synchronized liabilities | Not distinguishable in the empty result |
| Mortgage, consumer, revolving, unlinked, real-estate, and SCPI coverage | Not evidenced by a representative record or completeness contract |
| Stable liability identity | Not observed |
| Outstanding-balance and sign semantics | Not observed |
| Explicit EUR provenance | Not observed |
| Active/closed/deleted lifecycle | Not observed |
| Cross-surface and cross-membership deduplication | Not observed |
| Pagination completeness | Not proven |
| Known-empty semantics | Not guaranteed, despite current-value reconciliation |
| Authoritative total reconciliation | Current empty state reconciled exactly within `0.01` EUR |
| No unresolved category outside the collection | Not proven |

The official Finary loan documentation confirms that loans may be synchronized
or manually entered and may be linked to real estate or SCPI. The live empty
list gives no evidence that all of those paths converge into this collection,
nor that `false` UI warning flags would mean complete coverage rather than the
absence of those particular warnings.

## Decision

Phase 7 and the authorized Phase 9 follow-up conclude with **Outcome B: no
verified complete liability source**. The live organization-scoped surface is
callable, but its empty result cannot establish the missing identity, value,
currency, lifecycle, duplication, pagination, and known-empty semantics.
Schema `1.0` remains fail-safe: the production adapter raises
`FinaryFeatureUnavailableError`, and `GET /v1/snapshot` returns
`FINARY_FEATURE_UNAVAILABLE`. It does not emit a zero liability total or net
worth.

This conclusion means that available evidence is insufficient to claim
complete coverage. It does not claim that Finary has no loan data.

## Sources inspected

### `finary_uapi` release and source

- Package: `finary-uapi` `0.2.3`, published on 2026-03-11.
- Tag and source revision:
  [`v0.2.3` / `be147ce47eb0acb3b8f2b1d2152c551953e775bd`](https://github.com/lasconic/finary_uapi/tree/be147ce47eb0acb3b8f2b1d2152c551953e775bd).
- The upstream `main` revision inspected during Phase 7 was the same commit.
- The package is not installed as a runtime dependency of this bridge. The
  bridge uses `curl-cffi` directly and was compared with this exact source.

The source implements `GET` readers for legacy user-scoped holding accounts,
real estate, SCPI, and other asset collections. It has no liability/loan module,
no `get_liabilities()` implementation, and no private endpoint path for loans,
mortgages, or debt. The README advertises a `loans` CLI command, but the command
dispatcher contains no `loans` branch and imports no loan reader. Its TODO also
states that loan write/update/delete support is unfinished. The advertised
command is therefore not evidence of a callable read API.

The relevant legacy calls return the usual `{message, error, result}` envelope
with a list result. No pagination or completeness marker is implemented for
these asset readers. Previous sanitized live verification found `loans: []`
nested in holding-account, real-estate, and SCPI records. Those arrays were
empty, so the element schema, identity, currency, duplication, lifecycle, and
coverage semantics were not observed.

### Current organization-scoped traffic evidence

The Phase 7 review also inspected the traffic-derived FinaryExport analysis and
source at revision
[`2ba98b4e192d2f21f78232a79a6ff80b2885e1fa`](https://github.com/sailro/FinaryExport/tree/2ba98b4e192d2f21f78232a79a6ff80b2885e1fa).
That independent capture reports these read surfaces:

- `GET /organizations/{organization_id}/memberships/{membership_id}/portfolio/credits/accounts?period=...`
- `GET /organizations/{organization_id}/memberships/{membership_id}/portfolio?new_format=true&period=...`

The first is treated as a generic category-account list. The second reportedly
contains gross/net summaries and `has_unqualified_loans` and
`has_unlinked_loans` flags. Credit transactions have page-based pagination, but
the category-account reader inspected makes one list request and documents no
pagination or completeness metadata.

This is evidence that a newer credits surface exists; it is not sufficient
evidence that the surface is a complete stable liability collection. The
traffic-derived client maps credits through its generic account model and even
recomputes a unified net total by subtracting generic credit balances. It does
not define a dedicated non-empty loan schema or prove the EUR meaning of those
balances.

### Unofficial OpenAPI source

The older unofficial OpenAPI source at revision
[`bb0d8796d2f40a49abc066e3215813c90c192d52`](https://github.com/lasconic/openapi-finary/tree/bb0d8796d2f40a49abc066e3215813c90c192d52)
was also searched. It defines no loan/liability path. Its SCPI schema contains a
nested `loans` array whose item schema is explicitly left as a TODO. This adds
no evidence for identity, values, currency, completeness, or deduplication.

### Evidence classification

| Surface | Method and envelope | Evidence | Pagination/completeness |
| --- | --- | --- | --- |
| Legacy holding accounts, real estate, SCPI | `GET`; `{message, error, result}` list | Source-inspected and previously live-observed | No liability completeness marker; nested loans were empty |
| `finary_uapi loans` CLI entry | None | README text only; no dispatcher or reader | Not callable |
| Organization `credits/accounts` | `GET`; standard result envelope | Independently traffic-observed and source-inspected; not called by the Phase 7 bridge | Single list request in inspected client; no completeness marker |
| Organization portfolio overview | `GET`; standard result envelope | Independently traffic-observed and source-inspected; not called by the Phase 7 bridge | Loan-status flags observed, but no documented guarantee |
| Unofficial OpenAPI nested SCPI loans | Parent `GET` only | Source schema only | Item schema is TODO; no completeness semantics |

## Completeness assessment

Coverage is not considered complete because the inspected sources do not prove:

- that `credits/accounts` includes every Finary liability category, including
  manually entered and synchronized mortgages, consumer loans, credit cards,
  margin debt, and liabilities not linked to real estate;
- how organization memberships and shared liabilities must be combined without
  omissions or duplicates;
- whether a stable liability ID is available across all sources;
- whether linked loans repeated under accounts, real estate, or SCPI are the
  same record;
- how closed or deleted liabilities are represented;
- whether an empty list means complete zero coverage rather than unsupported,
  filtered, unauthorized, stale, or incomplete data;
- whether the account `balance` is an outstanding principal, its sign
  convention, or its currency provenance;
- whether the loan-status flags are completeness guarantees or only UI
  diagnostics;
- whether Finary's displayed net worth uses exactly the same set of records in
  every organization/membership context.

The [Finary loan guide](https://help.finary.com/en/articles/13526186-loans-complete-guide-to-track-your-loans)
confirms that loans can be synchronized or manually entered and may be linked
to property. That breadth reinforces why an
empty nested array or one generic credits category cannot be declared complete
without a representative observed structure and explicit coverage semantics.

## Current bridge behavior

`FinaryRawLiabilities` now carries an explicit adapter-owned coverage value:

- `COMPLETE`
- `PARTIAL`
- `UNAVAILABLE`

Only `COMPLETE` may reach schema `1.0` liability normalization. Consequently:

- `COMPLETE` plus an empty record tuple is a known-empty collection and may
  legitimately produce `liabilities_eur = 0` for deterministic injected tests;
- `PARTIAL` or `UNAVAILABLE`, even with an empty tuple, raises
  `FinaryFeatureUnavailableError` and cannot become zero;
- the live adapter still raises before returning a collection because it has no
  verified complete reader;
- a non-empty `COMPLETE` collection remains rejected until its field schema and
  EUR provenance have been verified.

No endpoint was added based on a guessed name. No nested `loans` array is read.

## Recommended versioned incomplete-coverage contract

The Phase 9 result recommends adopting the separately approved migration in
[`schema-v2-migration-plan.md`](schema-v2-migration-plan.md). Implement it as a new schema
major version and endpoint, for example `GET /v2/snapshot`. Do not change the
meaning of `GET /v1/snapshot`.

The smallest coherent proposal is:

```json
{
  "schema_version": "2.0",
  "coverage": {
    "liabilities": "COMPLETE"
  },
  "gross_assets_eur": 1000.0,
  "liabilities_eur": 100.0,
  "net_worth_eur": 900.0,
  "liabilities": []
}
```

Allowed liability coverage states would be `COMPLETE`, `PARTIAL`, and
`UNAVAILABLE`:

- `COMPLETE`: the liability collection is authoritative. An empty collection
  means known zero; `liabilities_eur` is the sum of normalized EUR liabilities,
  and `net_worth_eur` is calculated.
- `PARTIAL`: verified records may be returned for analysis, but
  `liabilities_eur` and `net_worth_eur` must be null because the complete total
  is unknown.
- `UNAVAILABLE`: no liability records or total are claimed;
  `liabilities_eur` and `net_worth_eur` are null.

A future migration would need explicit Sheets columns for coverage, revised n8n
validation/write rules, rules preventing partial data from deactivating a last
complete liability state, and a new compatibility test matrix. Those changes
are intentionally not part of Phase 7. The schema `1.0` Google Sheets JSON,
workbook columns, and n8n workflows remain unchanged.

## Live structural verification

The opt-in smoke test remains credential-gated and prints only the stable
liability status `NO VERIFIED COMPLETE SOURCE` or `COMPLETE SOURCE VERIFIED`.
It never prints endpoint payloads, values, IDs, names, addresses, or
authentication material. A fresh session may still require an interactive TOTP
or prepared email code; Phase 7 does not change that authentication behavior.

The Phase 9 probe called the candidate organization-scoped surfaces using the
protected Phase 8 session. It closed the prior callability gap but produced no
representative liability record and no completeness guarantee. Repeating the
same empty calls is unlikely to add material evidence. A future non-empty
response could establish record shape, but would still need an upstream-backed
scope and known-empty contract before schema `1.0` could claim `COMPLETE`.
