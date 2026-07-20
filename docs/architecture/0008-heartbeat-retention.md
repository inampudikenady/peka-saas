# ADR-0008: Heartbeat retention

**Status:** Accepted

## Decision

Keep accepted detailed heartbeats for 30 days. Periodic maintenance recalculates status independently of UI activity and removes older details. Lifecycle events remain available.

## Consequences

Storage is bounded for the initial release. Before long-range reporting is introduced, maintenance will aggregate hourly and daily availability/source metrics into rollup tables, then retain the same detailed deletion boundary.
