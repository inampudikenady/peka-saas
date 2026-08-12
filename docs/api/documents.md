# Connector document and Knowledge Service APIs

> Historical migration reference. These SaaS document endpoints are no longer
> registered in the normal application as of the customer-resident data-plane
> cutover. New uploads, indexing, deletion, and search use the Connector-local API.

## Connector upload

`POST /api/v1/connectors/{connector_id}/documents` is tenant-neutral at the HTTP routing layer. `Host` and `X-Forwarded-Host` are ignored for tenant selection. The bearer secret, path connector ID, and matching `X-PEKA-Connector-ID` authenticate one `ManagedConnector`; its persisted tenant ID is the only ownership source.

Headers:

```http
Authorization: Bearer <connector-secret>
X-PEKA-Connector-ID: <connector-id>
Idempotency-Key: <stable-operation-key>
Content-Type: multipart/form-data
```

Multipart parts:

- UPSERT uses multipart: `metadata` is JSON with `source_id`, `document_key`, `relative_path`, `filename`, `mime_type`, `size_bytes`, `content_hash`, `modified_at`, `operation`, and `connector_version`; `file` is the streamed binary.
- DELETE sends tombstone metadata as an `application/json` request body and omits `file`; `content_hash` and `modified_at` may be `null` because the persisted connector/document identity selects the tombstone target.
- `file`: required for `upsert`; omitted for `delete`.

`content_hash` is `sha256:<64 lowercase or uppercase hex characters>`. `modified_at` must carry a UTC offset. Supported extensions are `.txt`, `.md`, `.csv`, `.pdf`, `.docx`, and `.xlsx`. Ownership fields such as `tenant_id` and `connector_id` are rejected as unknown metadata.

Accepted upsert (`201`):

```json
{
  "accepted": true,
  "document_id": "<uuid>",
  "version_id": "<uuid>",
  "content_hash": "sha256:<verified-hash>",
  "ingestion_status": "RECEIVED"
}
```

Accepted delete uses `version_id: null`, `content_hash: null`, and `ingestion_status: "DELETE_RECEIVED"`.

The service reads the entire stream with a configured byte limit, computes SHA-256, compares declared size and hash, atomically writes the object, and commits metadata and the ingestion job before acknowledging. A failed write or mismatch is never acknowledged.

### Idempotency

Keys are durable in PostgreSQL and scoped to tenant plus connector. Exact replay returns the stored acknowledgement and creates no new version or job. Reusing a key with different metadata returns `409`. Records expire after the configured retention (24 hours by default); identical content for the same logical document also reuses its existing version.

Logical identity is `(tenant_id, document_key)`. `document_key` is the source-native
logical path/key and is independent of the connector appliance that delivered it.
`source_id`, `created_by_connector_id`, `last_seen_by_connector_id`, and
`last_synchronized_at` are synchronization provenance. A replacement connector
re-observing the same hash reuses the existing version, chunks, and vectors. A
content hash change creates a new immutable version.

Retiring a connector disables its credentials but does not delete documents,
versions, chunks, embeddings, or vectors. Tenant document responses expose source
freshness as `current`, `stale`, or `historical`; permanent knowledge deletion is
still an explicit tenant-administrator document action.

## Connector status feedback

`GET /api/v1/connectors/{connector_id}/documents/status?limit=100` uses the same connector authentication and returns a bounded set of safe current states and errors. `limit` is constrained to 1–200. A 30–60 second polling cadence is appropriate while work is pending; clients should back off after terminal states.

## Tenant retrieval

`POST /api/v1/tenant/search` requires an authenticated tenant user:

```json
{"query":"password policy","top_k":8,"filters":{"connector_id":null,"source_id":null,"document_id":null}}
```

`top_k` is limited to 25. Knowledge Service always injects the authenticated tenant into the Qdrant filter, validates optional filters against PostgreSQL ownership, and maps hits back through active PostgreSQL documents, current versions, and chunks. Results use the generic `knowledge_id`, `source_type`, `title`, `text`, `score`, `citation`, and `metadata` shape. Deleted documents, inactive versions, or untrusted vector payloads are excluded.

Embedding or vector providers that are not configured return a safe `503`; unrelated management APIs remain healthy. Future AI code must call Knowledge Service and must not query Qdrant directly.

## Tenant document management

Tenant administrators can list `GET /api/v1/tenant/documents` and inspect `GET /api/v1/tenant/documents/{document_id}`. List and detail responses include chunk count, embedding state, indexed state, and searchable state; details also include version history, parser/chunker/embedding provenance, storage state, and safe errors. Administrators may call `POST .../{id}/retry`, `POST .../{id}/reindex`, and `DELETE .../{id}`. Retry resumes `CHUNKED`/`NOT_CONFIGURED` versions at embedding after a provider is configured. Each mutation is tenant-scoped, audited, and avoids duplicate active stage jobs. Read-only tenant roles cannot view the operational inventory or mutate it.

`GET /api/v1/tenant/documents/{document_id}/pipeline-validation?query={expected_text}`
is a tenant-admin diagnostic. It reports PostgreSQL document/current-version
identity, source object presence, parsed-section and chunk counts, embedding
provenance, exact tenant/document/version-filtered Qdrant point count,
Knowledge Service result count, expected current-version retrieval, an overall
`searchable` flag, and safe issues. It never accepts a tenant selector and never
returns provider credentials.

Structured connector errors use `{ "code": "...", "message": "..." }`, including `INVALID_CONNECTOR`, `CONNECTOR_RETIRED`, `INVALID_DOCUMENT_METADATA`, `UNSUPPORTED_FILE_TYPE`, `SIZE_MISMATCH`, `HASH_MISMATCH`, `MIME_MISMATCH`, `INVALID_DOCUMENT_KEY`, `IDEMPOTENCY_CONFLICT`, `STORAGE_UNAVAILABLE`, `DOCUMENT_NOT_FOUND`, and `VALIDATION_FAILED`.
