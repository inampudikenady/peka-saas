
ADR-0002: Tenant Model

Status: Accepted

Context

PEKA is a multi-tenant SaaS platform where every customer organization must remain logically isolated.

Decision

A Tenant represents a customer organization.

Each tenant owns:

* Users
* Connectors
* Identity Providers
* Knowledge Sources
* AI Assistants
* Conversations
* Audit Events
* Platform Settings

Every business entity must belong to a tenant unless it is explicitly platform-wide.

Each tenant has:

* Permanent internal UUID
* Human-readable name
* URL slug
* Operational status

The UUID is the permanent system identifier.

The slug is used only for user-facing routing.

Example:

* UUID: 550e8400-e29b-41d4-a716-446655440000
* Slug: vitwo
* URL: https://vitwo.peka.com

Rationale

Separating the internal identifier from the public URL allows customers to rename or rebrand without affecting internal relationships.

Consequences

Database relationships use the tenant UUID.

Routing resolves a tenant slug into the corresponding tenant UUID.

Authentication, authorization, and data isolation are performed using the tenant UUID rather than the slug.
