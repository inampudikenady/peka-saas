ADR-0003: Connector Architecture

Status: Accepted

Context

Enterprise customers host infrastructure inside private networks protected by firewalls.

PEKA must operate without requiring inbound firewall access.

Decision

The PEKA Connector is an installation that may be deployed as:

* Docker container
* Virtual machine

Future deployment models may include Kubernetes or additional supported environments.

The connector communicates only through outbound HTTPS (TCP 443).

The connector registers with the SaaS using a one-time registration token.

After successful registration, the SaaS issues:

* Permanent Connector ID
* Connector credentials used for future authentication

The SaaS authenticates connectors using issued credentials rather than MAC addresses or other hardware identifiers.

Hardware information may be collected as metadata for operational awareness but is not treated as identity.

Heartbeat

Default heartbeat interval:

* Every 5 minutes

Operational states:

* Healthy
* Warning
* Offline
* Retired

Suggested thresholds:

* Warning after 15 minutes without a heartbeat
* Offline after 30 minutes without a heartbeat
* Retired after 30 days without a heartbeat

Work Execution

The SaaS never initiates inbound communication to the connector.

Instead:

1. SaaS creates a pending job.
2. Connector polls for work.
3. Connector executes locally.
4. Connector uploads results.

This preserves an outbound-only communication model.

Version Management

Connector upgrades are customer-controlled.

The SaaS reports:

* Installed version
* Latest available version
* Upgrade availability

Automatic upgrades are not enabled in the initial platform release.

Rationale

This architecture provides:

* Enterprise firewall compatibility
* Strong security boundaries
* Support for multiple deployment types
* Independent evolution of the SaaS and Connector

Future Considerations

Future releases may support certificate-based authentication, automated credential rotation, and additional deployment targets without changing the core architecture.
