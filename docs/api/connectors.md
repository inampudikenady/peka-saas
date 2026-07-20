# Connector API v1

All timestamps are timezone-aware ISO-8601 UTC values. Unknown fields follow FastAPI/Pydantic defaults. Neither API ever returns a stored credential hash.

## Register

`POST /api/v1/connectors/register`

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

The secret is returned once. The registration token determines the tenant; a connector cannot submit a tenant ID. Active duplicate `(tenant_id, instance_id)` registrations return `409`. Errors are `400` for malformed payloads, `401` for unknown credentials, `403` for inactive/not-permitted tenants, `409` for used tokens or duplicates, `410` for expired/revoked tokens, and `429` for rate limiting.

## Heartbeat

`POST /api/v1/connectors/{connector_id}/heartbeat`

Required headers:

```text
Authorization: Bearer <connector_secret>
X-PEKA-Connector-ID: <connector_id>
```

```json
{
  "instance_id": "uuid",
  "connector_version": "string",
  "timestamp": "ISO-8601 UTC timestamp",
  "status": "healthy",
  "uptime_seconds": 12345,
  "sources": { "total": 1, "healthy": 1, "unhealthy": 0, "disabled": 0 },
  "capabilities": ["filesystem_documents"]
}
```

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

> Connected means the connector is communicating with PEKA SaaS. It does not mean source data has been uploaded or synchronized.

## Tenant management

- `GET /api/v1/tenant/connectors`
- `GET /api/v1/tenant/connectors/{connector_id}`
- `POST /api/v1/tenant/connectors/{connector_id}/retire` (tenant admin)
- `POST /api/v1/tenant/connectors/registration-tokens` (tenant admin)
- `GET /api/v1/tenant/connectors/registration-tokens`
- `DELETE /api/v1/tenant/connectors/registration-tokens/{token_id}` (tenant admin)

The create response alone includes `registration_token`; list responses never do.

## Platform inventory

- `GET /api/v1/platform/connectors`
- `GET /api/v1/platform/connectors/{connector_id}`

Both platform roles may read. Neither endpoint mutates tenant state or exposes credentials.
