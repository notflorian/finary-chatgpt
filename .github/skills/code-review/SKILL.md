# Code Review Skill

Use this skill when reviewing a pull request or proposed code change in this repository.

## Purpose

Perform a repository-aware review that identifies concrete correctness, regression, security, data-integrity, compatibility, and contract violations. Follow the repository-wide rules in `AGENTS.md` and the review expectations in `.github/copilot-instructions.md`; do not restate them here.

## Review procedure

1. Read the pull request description, linked issue, and changed files before forming conclusions.
2. Derive the intended behavior from the issue acceptance criteria, the existing implementation, tests, and authoritative contracts referenced by `AGENTS.md`.
3. Trace each changed execution path far enough to understand its callers, downstream consumers, and relevant failure boundaries. Do not review isolated lines when behavior depends on surrounding control flow.
4. For every claimed fix, verify all independently reachable paths for the same failure class. Look for sibling call sites, alternate routes, retries, copies, normalization steps, persistence boundaries, and partial-success paths that may bypass the fix.
5. Compare the implementation against pre-existing invariants rather than only against the new tests. Flag changes that make tests pass by weakening validation, changing error semantics, swallowing failures, or silently discarding data.
6. Review negative behavior explicitly. Consider malformed input, missing fields, partial upstream responses, exceptions, retries, duplicate identifiers, stale state, incompatible runtime behavior, and failed persistence where relevant to the diff.
7. Check whether tests demonstrate the behavior at the correct boundary. Prefer deterministic fault injection for exception translation and bounded realistic fixtures for parser, copy, normalization, and API behavior. Avoid tests that depend on interpreter-specific resource limits unless the behavior itself is version-specific.
8. Check that regression tests distinguish the root cause from nearby behavior. A test should fail for the defect it claims to cover and should not succeed merely because execution exits earlier for an unrelated reason.
9. Inspect changed logging and error handling for information disclosure. Review both response bodies and logs when secrets, session state, upstream payloads, or exception details could escape.
10. Inspect compatibility implications across supported Python versions, API versions, stored state, generated workflow artifacts, and downstream workbook contracts when the changed code touches those surfaces.
11. Review the final diff for unnecessary scope expansion, duplicated logic, dead code, inconsistent abstractions, or changes to unrelated behavior.

## Evidence standard

Only report a finding when you can identify a concrete failure mode or a clear violation of an established contract.

For each finding:

- identify the affected path and condition
- explain the observable consequence
- explain why existing tests or guards do not prevent it
- cite the relevant changed lines when possible
- state the narrowest reasonable correction direction without prescribing an unrelated refactor

Do not report speculative style preferences, hypothetical issues without a reachable scenario, or concerns already fully prevented by surrounding code.

## Severity calibration

Use severity according to impact and likelihood:

- `P0`: immediate catastrophic impact such as destructive data corruption, critical secret exposure, or a broadly exploitable security failure
- `P1`: high-impact production breakage, serious data-integrity failure, authentication or authorization failure, or a common path becoming unusable
- `P2`: meaningful correctness or reliability bug affecting a realistic subset of executions, including incorrect state, broken error contracts, partial success, or important regression risk
- `P3`: lower-impact but real defect with a reproducible edge case, incomplete robustness, or maintainability problem likely to cause incorrect behavior later

Do not inflate severity because a code path is security-sensitive or because the fix is complex. Base severity on the actual consequence of the defect.

## Completion criteria

Before finishing the review:

- verify every issue acceptance criterion against the implementation or tests
- check whether the change introduces a new failure mode while fixing the reported one
- confirm that relevant error and partial-success paths were considered
- distinguish repository defects from interpreter, dependency, or environment-specific behavior
- avoid duplicate findings that share the same root cause
- omit a finding when the available evidence is insufficient

If no actionable defect is found, return a clean review rather than manufacturing comments.