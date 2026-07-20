# ADR-0006: Connector bearer secret hashing

**Status:** Accepted

## Decision

Registration generates a 384-bit random bearer secret and returns it once. SaaS stores only an Argon2 hash and uses password-hash verification for authentication. Unknown IDs execute a dummy verification. The path ID and `X-PEKA-Connector-ID` must match.

## Consequences

Secrets cannot be recovered or redisplayed. Rotation is intentionally deferred and will require a separately authorized lifecycle, not exposing the current hash.
