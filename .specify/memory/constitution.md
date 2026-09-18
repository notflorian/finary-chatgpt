# Finary ChatGPT Constitution

## Core Principles

### I. Official MCP Boundary
The bridge MUST use only official Finary MCP and keep provider transport, OAuth,
resource relationships, and error translation inside its adapter boundary. n8n
MUST receive normalized bridge data only. This preserves a single supported source
and prevents credentials or provider-specific behavior from spreading downstream.

### II. Truthful Financial Semantics
Financial observations MUST preserve known values, source provenance, ownership,
coverage, and exact decimal meaning. EUR fields require proven EUR or verified
conversion; unknown values remain null rather than becoming zero. Official totals
and allocation retain their own authority. This prevents a convenient display value
or incomplete detail from becoming an asserted financial fact.

### III. Fail-Closed Observations and Deterministic Workbooks
Snapshots, identities, schemas, prepared rows, and terminal membership MUST be
validated before portfolio writes or consumption. Malformed or incomplete data MUST
not alter the last valid portfolio state. Current rows use deterministic upserts,
accepted history stays immutable, and manual sheets remain operator-owned. This
keeps retries, readback, and recovery evidence trustworthy.

### IV. Credential and Operator-Data Isolation
Credentials, tokens, raw private payloads, and operator data MUST stay in their
assigned boundary: Finary OAuth state belongs only to the bridge, and Google OAuth
belongs only to n8n. Fixtures and ordinary checks use synthetic anonymized data.
This limits disclosure and keeps normal development independent of live services.

### V. Focused, Evidence-Backed Changes
Changes MUST preserve supported contracts and remain as narrow as the requested
outcome permits. The implementation, fixtures, and canonical schema take precedence
over conflicting prose; relevant credential-free tests, documentation links, and the
final diff provide the evidence for a change. This maintains stable interfaces
without speculative redesign or duplicate sources of truth.

## Canonical References

This constitution summarizes durable governance; it does not duplicate field lists,
commands, runbooks, or contract definitions. [AGENTS.md](../../AGENTS.md) directs
repository work. The [architecture](../../docs/architecture.md),
[source contract](../../docs/finary-mcp-contract.md),
[workbook schema](../../docs/google-sheets-schema.json),
[development guide](../../docs/development.md), and
[operations guide](../../docs/operations.md) own their respective technical and
operational details.

## Development Practice

Routine work continues directly from issue to implementation, relevant tests, diff
inspection, and pull request. Spec Kit is optional when a feature benefits from
durable specification, planning, task breakdown, or cross-artifact analysis; its
active feature context is independent of Git branch naming. See the
[Spec Kit onboarding](../../docs/development.md#optional-spec-kit-workflow) before
using planning or analysis commands.

## Governance

This constitution distills, but does not replace, `AGENTS.md` and the canonical
contracts and guides above. Amend it only through a focused documentation change
whose principles remain traceable to existing repository rules. Use semantic
versioning for constitution changes: MAJOR for incompatible principle removal or
redefinition, MINOR for a new or materially expanded principle, and PATCH for a
clarification. Reviews MUST check the relevant implementation and documentation
against these principles. A constitution change does not authorize publication,
deployment, workflow activation, or changes to operator data.

**Version**: 1.0.0 | **Ratified**: 2026-09-18 | **Last Amended**: 2026-09-18
