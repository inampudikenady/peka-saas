# ADR-0001: Platform Boundary

**Status:** Accepted

## Context

PEKA is being designed as a commercial multi-tenant SaaS platform for enterprise customers.

Customers operate infrastructure inside private networks that PEKA cannot directly access.

## Decision

PEKA SaaS is the platform control plane.

The SaaS is responsible for:

- Tenant management
- Authentication and authorization
- Identity providers (SSO)
- User management
- Connector management
- AI orchestration
- Conversation history
- Platform configuration
- Audit logging
- Licensing (future)

The SaaS is **not** responsible for directly communicating with customer infrastructure.

All interaction with customer systems occurs through a PEKA Connector installed inside the customer's environment.

## Rationale

This provides:

- Clear security boundaries
- Enterprise-friendly firewall requirements
- Independent evolution of the SaaS and Connector
- A scalable multi-tenant architecture

## Consequences

The SaaS never initiates inbound connections to customer environments.

The connector always initiates outbound communication over HTTPS.

All future integrations with Prometheus, Loki, CMDBs, ticketing systems, VMware, cloud providers, or other enterprise systems will be implemented through the connector.

## Future Considerations

The platform may support multiple connector types while maintaining the same control-plane architecture.
