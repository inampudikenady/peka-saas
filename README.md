# PEKA SaaS

Commercial multi-tenant SaaS platform for PEKA.

This repository contains the SaaS control plane responsible for:

- Tenants
- Users
- Authentication
- Connector registration
- Connector document ingestion and versioning
- Parsing, chunking, embedding, and tenant-scoped retrieval
- Knowledge Service retrieval with structured citations
- Audit logging
- Platform APIs
- Web UI

The enterprise connector will live in a separate repository.

## Connector management

PEKA SaaS implements the connector control-plane lifecycle:

- Tenant administrators generate 30-minute, single-use registration tokens under `/api/v1/tenant/connectors/registration-tokens`.
- Appliances register through `POST /api/v1/connectors/register` and receive a connector ID and one-time connector secret.
- Appliances report health through `POST /api/v1/connectors/{connector_id}/heartbeat` every 300 seconds.
- Tenant users see only their tenant's inventory. Platform administrators and platform read-only users have cross-tenant read-only inventory.
- Status is derived by SaaS and refreshed by heartbeats, reads, and a background maintenance loop.

Raw registration tokens and connector secrets are never stored. See [Connector API](docs/api/connectors.md), [security](docs/security/connectors.md), and [database design](docs/database/connectors.md).

## Document ingestion

Authenticated connectors upload supported documents through `POST /api/v1/connectors/{connector_id}/documents`. The API verifies the complete byte stream and SHA-256 before atomically storing the object and committing document/version/job metadata. A separate staged worker parses, chunks, embeds, and indexes accepted versions in Qdrant. Tenant administrators inspect operational document state under Administration → Documents; authenticated tenant users search through the Knowledge Service.

Documents and indexed knowledge are tenant-owned. Connector IDs are retained only
as producer/synchronization provenance, so connector retirement or replacement
does not duplicate or delete unchanged tenant knowledge.

PostgreSQL and object storage are the system of record. Qdrant is a rebuildable, tenant-filtered derived index. See the exact [Document API contract](docs/api/documents.md) and [document pipeline architecture](docs/architecture/0009-document-ingestion-and-retrieval.md).

## Local verification

```shell
cd backend && DEBUG=false .venv/bin/pytest -q
cd frontend && npm test && npm run lint && npm run build
docker compose build
```

Start persistent local Qdrant alone with `docker compose -f docker-compose.qdrant.yml up -d`, while continuing to run the backend, worker, and frontend natively. Configure a real OpenAI-compatible embedding provider through environment variables before starting the worker; deterministic fake vectors are restricted to `ENVIRONMENT=test`. If no provider is configured, documents remain safely at `CHUNKED` with `NOT_CONFIGURED`. The copy-pasteable macOS procedure, health checks, Make targets, worker command, retry semantics, and troubleshooting guide are in [Local knowledge ingestion](docs/development/knowledge-ingestion.md).
