# ADR-0005: Connector registration tokens

**Status:** Accepted

## Decision

Tenant administrators issue tenant-bound, revocable, single-use random tokens with a 30-minute default lifetime. SaaS stores a deterministic SHA-256 digest because the raw value has 256 bits of entropy and lookup must occur before tenant identity is known. The raw token is returned only by create.

## Consequences

Compromise of the database does not reveal usable tokens. Generation, revocation, use, expiry, and attributable failed use produce connector events. Multi-use and expired/revoked attempts have explicit HTTP outcomes.
