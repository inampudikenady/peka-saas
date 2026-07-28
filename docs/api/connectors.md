# Connector API v1

All timestamps are timezone-aware ISO-8601 UTC values and include either `Z` or `+00:00`. Registration rejects unknown request fields. Neither API ever returns a stored credential hash.

## Register

`POST /api/v1/connectors/register`

Connector registration is tenant-neutral at the HTTP routing layer. The one-time registration token securely determines the tenant.

The endpoint does not perform tenant hostname or path resolution. `Host` values supplied by reverse proxies—including loopback and internal service hosts—do not select or block a tenant. `X-Forwarded-Host` is not trusted for connector tenant selection, and `tenant_id` is not accepted in the request body.

```json
{
  "registration_token": "string",
  "connector_name": "string",
  "connector_version": "string",
  "environment": "string",
  "instance_id": "uuid",
  "capabilities": ["filesystem_documents"]
}
```

Success (`201`):

```json
{
  "connector_id": "uuid",
  "tenant_id": "uuid",
  "connector_secret": "string",
  "heartbeat_interval_seconds": 300,
  "registered_at": "ISO-8601 UTC timestamp"
}
```

The secret is returned once. The registration token determines the tenant; a connector cannot submit a tenant ID. Active duplicate `(tenant_id, instance_id)` registrations return `409`.

Every registration rejection uses the same response shape:

```json
{
  "code": "TOKEN_EXPIRED",
  "message": "The registration token has expired."
}
```

| HTTP status | Code | Meaning |
| --- | --- | --- |
| `401` | `TOKEN_NOT_FOUND` | The supplied credential could not be validated. The message is deliberately generic. |
| `410` | `TOKEN_EXPIRED` | The one-time token has expired. |
| `410` | `TOKEN_USED` | The one-time token was already consumed. |
| `410` | `TOKEN_REVOKED` | The one-time token was revoked. |
| `409` | `INSTANCE_ALREADY_REGISTERED` | An active connector for the token's tenant and appliance instance already exists. |
| `403` | `TENANT_MISMATCH` | A defensive tenant-binding check failed. The request cannot provide a tenant ID. |
| `403` | `TENANT_INACTIVE` | The token's tenant is suspended or retired. |
| `409` | `CONNECTOR_LIMIT_REACHED` | The configured active-connector limit for the tenant has been reached. |
| `403` | `REGISTRATION_NOT_PERMITTED` | The validated token references an unavailable tenant record or a future explicit registration policy denies the operation. |
| `422` | `VALIDATION_FAILED` | The request body does not match the registration contract, including any attempted `tenant_id` override. |
| `429` | `RATE_LIMITED` | The client exceeded the registration-attempt limit. |
| `500` | `INTERNAL_ERROR` | An unexpected server failure occurred. |

`TOKEN_HASH_MISMATCH` is reserved in the typed contract for credential verification implementations that can distinguish a stored-record hash mismatch. The current deterministic secure-hash lookup deliberately maps an unrecognized credential to the generic external `TOKEN_NOT_FOUND` response, so callers cannot enumerate token records.

Registration diagnostics record the request ID, appliance instance ID, resolved tenant ID, registration-token record ID, rejection code, and a credential-safe `internal_reason` when each value is available. Internal reasons distinguish inactive or missing tenants, configured connector limits, duplicate-instance conflicts, token lifecycle failures, validation failures, and database failures without exposing them to connector callers. Raw registration tokens, connector secrets, stored token hashes, and other recoverable credentials are never logged. Rejections are logged before their response is returned.

## Heartbeat

`POST /api/v1/connectors/{connector_id}/heartbeat`

Heartbeat routing is also tenant-neutral. After bearer verification, SaaS obtains the tenant from the stored managed connector record; neither `Host` nor `X-Forwarded-Host` participates in connector identity.

Required headers:

```text
Authorization: Bearer <connector_secret>
X-PEKA-Connector-ID: <connector_id>
```

```json
{
  "instance_id": "uuid",
  "connector_name": "VITWO Production Connector",
  "connector_version": "string",
  "environment": "production",
  "timestamp": "ISO-8601 UTC timestamp",
  "status": "healthy",
  "uptime_seconds": 12345,
  "sources": { "total": 1, "healthy": 1, "unhealthy": 0, "disabled": 0 },
  "capabilities": ["filesystem_documents"]
}
```

`connector_name` and `environment` are optional for backward compatibility with earlier appliances. When present on an authenticated heartbeat, they replace the managed connector's display name and environment. `connector_version` and capabilities are updated on every accepted heartbeat. Registration and heartbeat also accept `name` as an alias for `connector_name`, and `version` as an alias for `connector_version`.

Success (`200`):

```json
{
  "accepted": true,
  "server_time": "ISO-8601 UTC timestamp",
  "next_heartbeat_seconds": 300
}
```

The source counts must be non-negative and sum to `total`. The path, header, bearer secret, and registered instance ID must agree. `status` is a process-health observation and does not set authoritative SaaS status.

## Current SaaS status semantics

- `connected`: a recent authenticated heartbeat was received and no sources reported unhealthy.
- `degraded`: a recent authenticated heartbeat was received and one or more sources reported unhealthy.
- `out_of_sync`: the last successful heartbeat is older than 1.5 intervals but less than 3 intervals.
- `disconnected`: no successful heartbeat has been received, or it is at least 3 intervals old.
- `authentication_failed`: three recognized authentication failures were recorded for a known connector.
- `retired`: the connector was explicitly retired.

`in_sync` remains reserved for forward compatibility but is not currently derived or presented. It will require evidence that connector data has actually synchronized to SaaS.

> Connected means the connector is communicating with PEKA. It does not mean source data has been uploaded or synchronized.

## Tenant management

- `GET /api/v1/tenant/connectors?include_retired=false`
- `GET /api/v1/tenant/connectors/{connector_id}`
- `POST /api/v1/tenant/connectors/{connector_id}/retire` (tenant admin)
- `POST /api/v1/tenant/connectors/registration-tokens` with an empty body or `{}` (tenant admin)
- `GET /api/v1/tenant/connectors/registration-tokens?include_inactive=false`
- `DELETE /api/v1/tenant/connectors/registration-tokens/{token_id}` (tenant admin)

The create response alone includes `registration_token`; list responses never do.

Connector inventories exclude only retired records by default; every non-retired operational state remains visible. Set `include_retired=true` to include history. Registration-token lists return only unused, unrevoked, unexpired credentials by default; set `include_inactive=true` to include used, expired, and revoked records.

New registration tokens do not accept or store a connector name. Historical records may still contain `intended_connector_name`; it remains readable audit/reference metadata only and is never an authorization constraint. The appliance-submitted registration name becomes the managed connector's display name, and later authenticated heartbeat names replace it. Deployments may optionally set `CONNECTOR_MAX_ACTIVE_PER_TENANT`; it is unlimited when omitted.

## Platform inventory

- `GET /api/v1/platform/connectors?include_retired=false`
- `GET /api/v1/platform/connectors/{connector_id}`

Both platform roles may read. Neither endpoint mutates tenant state or exposes credentials.
