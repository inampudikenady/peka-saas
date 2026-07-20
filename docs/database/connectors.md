# Connector database model

`managed_connectors` is the tenant-owned appliance identity. A PostgreSQL partial unique index on `(tenant_id, instance_id) WHERE retired_at IS NULL` prevents concurrent active duplicates. Tenant/status and tenant list indexes support inventory reads.

`connector_registration_tokens` stores only a SHA-256 digest of a 256-bit random value. It tracks expiry, use, revocation, creator, optional intended name, and lazy expiration-audit state. The digest is unique and indexed for registration lookup.

`connector_capabilities` contains one tenant-stamped row per `(connector_id, capability)`. Heartbeats replace the reported set transactionally.

`connector_heartbeats` stores accepted detailed observations, indexed by `(connector_id, received_at)`. Details older than 30 days are deleted by maintenance. A future rollup table can retain hourly/daily availability and source-health aggregates before deletion.

`connector_events` is the immutable lifecycle/audit stream for token, registration, heartbeat, source, status, authentication, and retirement events. Event details contain no credentials.

Migration `f0c91d7a4e22` creates both PostgreSQL enums, all five tables, foreign keys, checks, tenant indexes, history indexes, and the active-instance partial unique index.
