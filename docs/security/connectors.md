# Connector security

- Registration tokens use `secrets.token_urlsafe(32)` and a recognizable non-secret prefix. Only their SHA-256 lookup digest is stored; high entropy prevents offline enumeration.
- Connector secrets use `secrets.token_urlsafe(48)`. Only an Argon2 password hash is stored and verification uses the hash implementation's constant-time verification path. A dummy hash is verified for unknown IDs to reduce identity timing disclosure.
- Raw values are returned once, omitted from models/list/detail responses, and never logged or placed in event detail.
- Registration credentials select the tenant. The public payload cannot choose or override it.
- Tenant repository methods require `tenant_id`; cross-tenant detail reads intentionally return not found.
- Tenant users can view inventory. Only `tenant_admin` can generate/revoke tokens or retire connectors. Both platform roles can view global inventory; neither platform connector route mutates tenant records.
- Registration is limited to 10 attempts per client per five minutes. Heartbeats are limited to 30 per client/connector per minute. The in-process limiter is suitable for the current single API replica; distributed deployments must move counters to Redis or an API gateway.
- Three invalid bearer attempts on a known active connector derive `authentication_failed`. Responses use a generic authentication failure and do not disclose connector existence.
- Retired credentials cannot authenticate. Secrets are never available to the UI.

Connector status does not assert data synchronization. Healthy source reports mean the connector can locally read and scan those sources. `In Sync` is reserved for a future data-upload lifecycle and is neither derived nor displayed today.

> Connected means the connector is communicating with PEKA SaaS. It does not mean source data has been uploaded or synchronized.
