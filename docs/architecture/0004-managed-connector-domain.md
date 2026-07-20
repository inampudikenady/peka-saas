# ADR-0004: ManagedConnector domain model

**Status:** Accepted

## Decision

The SaaS appliance record is named `ManagedConnector`. It is tenant-owned and identified by an immutable SaaS UUID plus customer-generated `instance_id`. Active `(tenant_id, instance_id)` pairs are unique; names need not be. Capabilities, observations, and events are separate entities so the identity record remains a current-state projection.

## Consequences

Every tenant query carries tenant ID. Retirement is soft and preserves operational history. Re-registration after retirement can create a new managed record without silently duplicating an active appliance.
