# Document ingestion database model

Migrations `a13f4c8d7e21` and `b24d9e6f1a32` add and refine the knowledge-ingestion schema without resetting existing SaaS data.

- `documents` is the connector-scoped logical identity and soft-deletion tombstone.
- `document_versions` stores immutable hashes, object keys, processing versions/status, timestamps, and safe errors.
- `document_parsed_sections` persists normalized structured parser output between stages.
- `ingestion_jobs` is the durable staged queue with attempts, locks, retry time, correlation ID, stale-lock recovery, and a unique active version/stage constraint.
- `document_chunks` stores extracted text and citation metadata in PostgreSQL; Qdrant point IDs are stable UUIDv5 values.
- `document_idempotency_records` stores request fingerprints, document/version references, HTTP status, and acknowledgements, never files or credentials.
- `document_audit_events` records tenant-admin retry, re-index, and soft-delete requests.
- `ingestion_worker_heartbeats` supports worker and stale-job diagnostics.

All ownership-bearing rows include `tenant_id` and all application lookups require it. Connector/document/version foreign keys cascade only within their persisted relationships. The logical-document uniqueness constraint is `(tenant_id, connector_id, source_id, document_key)` and version uniqueness is `(document_id, content_hash)`.

Deletion marks the document deleted and asynchronously removes its Qdrant points. Stored source objects and historical versions are retained initially for audit/recovery; production storage lifecycle and hard-deletion policy must be set before regulated deployment.
