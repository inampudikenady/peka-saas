# Customer-resident Local Knowledge Store

## Decision

PEKA SaaS is the control plane. PEKA Connector v1.0.0 owns durable customer
documents, parsing, chunking, redaction, embedding, Qdrant, indexing status, and
semantic retrieval. SaaS never connects to customer Qdrant.

Chat creates a tenant- and user-authorized `knowledge_search` request using the
existing connector-authenticated outbound request channel. The active Connector
claims it, searches its Local Knowledge Store, and returns bounded relevant
chunks. SaaS clears the ephemeral result payload after orchestration.

## Operational metadata

The Connector heartbeat reports only status, document count, indexed chunk
count, and last indexing activity. These values are persisted on connector and
heartbeat records so Connector detail pages can show health without browsing
customer content.

## Historical data and rollback

The legacy SaaS `documents`, `document_versions`, `document_parsed_sections`,
`document_chunks`, `ingestion_jobs`, idempotency, audit, and worker-heartbeat
tables remain unchanged. Existing object storage and Qdrant volumes also remain.
They are migration-only and normal SaaS startup does not initialize them.

Migration sequence:

1. Inventory legacy PostgreSQL document/version rows and Qdrant points by tenant.
2. Export original objects or perform a controlled re-index from the customer source.
3. Import through the customer Connector and validate document/chunk counts plus sampled retrieval.
4. Switch retrieval to the Connector (implemented in this milestone).
5. Retain legacy data through the agreed rollback window.
6. Remove legacy content only in a separately approved, backed-up migration.

No collection, row, object, or Docker volume is deleted automatically.
