# ADR-0005: Connector registration tokens

**Status:** Accepted

## Decision

Tenant administrators issue tenant-bound, revocable, single-use random tokens with a 30-minute default lifetime. SaaS stores a deterministic SHA-256 digest because the raw value has 256 bits of entropy and lookup must occur before tenant identity is known. The raw token is returned only by create.

New registration tokens carry no connector name. The nullable legacy `intended_connector_name` column remains temporarily so historical records continue to load, but SaaS does not populate, display, compare, or authorize against it. The appliance-provided registration name becomes the `ManagedConnector` display name, and authenticated heartbeat metadata can update that display name later.

Connector registration is tenant-neutral at the HTTP routing layer. The one-time registration token securely determines the tenant.

Public registration and heartbeat routes bypass tenant hostname/path resolution before routing headers are inspected. Registration resolves the tenant from the validated token; heartbeat resolves it from the authenticated `ManagedConnector`. Connector APIs never trust `Host` or `X-Forwarded-Host` to choose a tenant, and registration does not accept `tenant_id`.

## Consequences

Compromise of the database does not reveal usable tokens. Generation, revocation, use, expiry, and attributable failed use produce connector events. Multi-use and expired/revoked attempts have explicit HTTP outcomes.

Public errors remain safe and stable while credential-safe internal registration diagnostics record a precise reason. Suspended or retired tenants and an optional deployment-wide active-connector limit have distinct public outcomes; missing tenant records and unexpected persistence failures remain non-disclosing internal failures.

Reverse proxies and Tailscale may forward a local or internal `Host` without affecting connector identity. Normal tenant UI and API routes retain the existing hostname/path resolution requirements.
