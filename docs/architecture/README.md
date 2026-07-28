# PEKA SaaS Architecture Decision Records (ADRs)

## Purpose

This directory contains Architecture Decision Records (ADRs) for the PEKA SaaS platform.

An ADR captures **why** a technical decision was made, not just **what** was implemented.

As the platform evolves, these documents provide historical context and help prevent architectural drift.

## ADR Format

Each ADR contains:

- Status
- Context
- Decision
- Rationale
- Consequences
- Future Considerations

## Numbering

Architecture decisions are numbered sequentially.

Example:

- 0001-platform-boundary.md
- 0002-tenant-model.md
- 0003-connector-architecture.md

New ADRs should never modify the intent of previous accepted decisions. If a decision changes, create a new ADR that supersedes the earlier one.

Connector lifecycle decisions are recorded in ADRs 0004–0008. ADR-0007 explicitly supersedes ADR-0003's original coarse status labels and fixed warning/offline thresholds.

ADR-0009 records the document system of record, asynchronous processing, provider boundaries, derived Qdrant index, and cited retrieval/AI flow.

The authoritative stateless grounded-answer design is documented in
[AI Answer Service Architecture v1](ai-answer-service.md).
