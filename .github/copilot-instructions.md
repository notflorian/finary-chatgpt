# GitHub Copilot instructions

These instructions complement `AGENTS.md`. Read and follow `AGENTS.md` and
`docs/architecture.md` before reviewing or changing code. Do not duplicate or
weaken repository-wide rules defined there.

## Code review priorities

Review for correctness, regressions, security, data integrity, API-contract
compatibility, failure semantics, and missing tests. Prefer substantive findings
over style-only comments.

When a pull request is linked to an issue, read the issue and verify every
acceptance criterion against the implementation and tests. Do not assume that a
passing test suite proves the issue is fully fixed.

Inspect the surrounding code when needed to validate invariants, call paths, and
error boundaries. Pay particular attention to independent failure paths that a
narrow fix may leave unhandled.

## Repository-specific checks

- Preserve the architectural boundaries documented in `AGENTS.md` and
  `docs/architecture.md`.
- Keep raw Finary response handling and exception translation inside the adapter
  boundary. FastAPI routes must remain HTTP boundaries rather than upstream
  protocol handlers.
- Verify structured API errors keep the documented status, error code, message,
  and retryability semantics and never expose credentials, session material,
  tokens, raw private payloads, stack traces, or implementation details.
- Treat partial or unavailable upstream data conservatively. A failed collection
  must not be reported as complete, silently converted to an empty success, or
  used to publish a partially valid snapshot.
- Check that authentication, token refresh, persisted-session ownership, CAS,
  replay/freshness protections, and replacement semantics are not weakened by
  unrelated changes.
- Preserve canonical identifiers, EUR provenance rules, liability coverage
  semantics, deterministic workbook behavior, historical-row preservation, and
  manual-sheet ownership.
- Verify `/v1/snapshot` remains fail-safe and `/v2/snapshot` remains backward
  compatible within schema major version 2 unless a coordinated breaking change
  is explicitly intended.
- Treat `docs/google-sheets-schema.json` as the machine-readable workbook
  contract when reviewing workflow or schema changes.
- Reject changes that weaken validation, safety limits, credential isolation, or
  error handling merely to make tests pass.

## Tests and regressions

Expect tests for both the successful path and relevant failure paths. For bug
fixes, require a regression test that would fail before the fix whenever that
can be done deterministically and without credentials or external services.

Do not require version-specific implementation behavior unless the repository
contract requires it. The project supports Python 3.12+, including Python 3.14,
so tests should prefer deterministic injection over assumptions about parser,
recursion, exception, or runtime thresholds that may vary by interpreter.

Fixtures must remain synthetic and anonymized. Normal tests must not contact
Finary, Google, or public services, read real credentials or session files,
prompt for MFA, modify live workbooks, publish workflows, or deploy anything.

When reviewing test coverage, consider at least the directly affected unit tests,
API tests, service tests, authentication/session regressions, and collection
completeness behavior where relevant.

## Finding quality

Only report a finding when there is a concrete defect, regression risk, missing
required behavior, or meaningful test gap. Avoid speculative comments that are
not tied to an observable failure mode or documented invariant.

For each finding:

1. Identify the exact changed code responsible.
2. Explain the failure scenario and user or system impact.
3. Reference the violated contract, invariant, or acceptance criterion when
   applicable.
4. Suggest the smallest safe correction without redesigning unrelated code.
5. Distinguish confirmed defects from assumptions that still require evidence.

Do not request unrelated refactors, formatting churn, new abstractions, or broad
cleanup in a focused bug-fix pull request unless they are necessary for
correctness or safety.
