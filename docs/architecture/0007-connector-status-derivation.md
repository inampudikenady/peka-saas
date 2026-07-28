# ADR-0007: Connector status derivation

**Status:** Accepted; supersedes the status labels and fixed thresholds in ADR-0003.

## Decision

SaaS derives status from successful receive time, expected interval, source summary, authentication failures, and retirement. It recalculates on heartbeat, list/detail reads, and a background maintenance loop.

- `Connected`: an authenticated heartbeat is at most 1.5 intervals old and no sources report unhealthy.
- `Degraded`: heartbeat is recent and at least one source is unhealthy.
- `Out of Sync`: age is over 1.5 but under 3 intervals.
- `Disconnected`: no successful heartbeat, or age is at least 3 intervals.
- `Authentication Failed`: at least three invalid secret attempts on a known connector.
- `Retired`: tenant administrator retired the record.

`In Sync` remains in the persistence enum for forward compatibility, but SaaS does not derive or display it. Local source health means only that the connector can read and scan the source. `In Sync` may be introduced only after connector-to-SaaS data upload exists and synchronization can be measured.

> Connected means the connector is communicating with PEKA. It does not mean source data has been uploaded or synchronized.

## Consequences

Connector process claims never set authoritative status. Process health, reachability, local source health, and future data synchronization remain separate concepts.
