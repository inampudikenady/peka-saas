# Local knowledge-ingestion runtime

PEKA runs the SaaS backend, ingestion worker, and frontend natively. Only
PostgreSQL and Qdrant are containerized for local development. The pipeline is:

`Connector → Document Service → object storage → worker → parser → chunks → embeddings → Qdrant → Knowledge Service`

The backend accepts uploads and creates PostgreSQL jobs; it does **not** process
those jobs. A standalone worker must be running.

## One configuration source

Copy `backend/.env.example` to `backend/.env`. `app.core.config.Settings`
resolves this exact file relative to the backend package, not the shell working
directory. Uvicorn, `app.scripts.run_ingestion_worker`, and every validation CLI
import the same cached Settings object. The frontend has no Qdrant, embedding,
worker, or object-storage configuration.

The knowledge settings consumed by the implementation are:

| Area | Variables |
|---|---|
| Runtime | `ENVIRONMENT`, `DATABASE_URL`, `LOG_LEVEL` |
| Objects | `PEKA_OBJECT_STORAGE_BACKEND`, `PEKA_OBJECT_STORAGE_LOCAL_ROOT`, `PEKA_INGESTION_MAX_UPLOAD_BYTES`, `PEKA_DOCUMENT_IDEMPOTENCY_HOURS` |
| Qdrant | `PEKA_QDRANT_URL`, `PEKA_QDRANT_COLLECTION`, `PEKA_QDRANT_API_KEY`, `PEKA_QDRANT_TIMEOUT_SECONDS`, `PEKA_QDRANT_TLS_VERIFY` |
| Embeddings | `PEKA_EMBEDDING_PROVIDER`, `PEKA_EMBEDDING_BASE_URL`, `PEKA_EMBEDDING_API_KEY`, `PEKA_EMBEDDING_MODEL`, `PEKA_EMBEDDING_DIMENSION`, `PEKA_EMBEDDING_BATCH_SIZE`, `PEKA_EMBEDDING_TIMEOUT_SECONDS` |
| Worker | `PEKA_INGESTION_WORKER_ENABLED`, `PEKA_INGESTION_WORKER_POLL_SECONDS`, `PEKA_INGESTION_WORKER_CONCURRENCY`, `PEKA_INGESTION_WORKER_STALE_JOB_SECONDS`, `PEKA_INGESTION_WORKER_HEARTBEAT_STALE_SECONDS` |
| Retry | `PEKA_INGESTION_JOB_MAX_ATTEMPTS`, `PEKA_INGESTION_RETRY_BASE_SECONDS`, `PEKA_INGESTION_RETRY_MAX_SECONDS` |

The example config uses local filesystem objects, Qdrant on port 6333, and
Ollama's OpenAI-compatible endpoint with `nomic-embed-text` at 768 dimensions.
Ollama needs no API key locally; PEKA adds an Authorization header only when
`PEKA_EMBEDDING_API_KEY` is nonempty. Never commit a real key.

The earlier degraded/pending condition had two independent causes:

1. the active backend `.env` had no Qdrant or embedding variables, so optional
   knowledge startup correctly reported degraded; and
2. no standalone worker was alive, so Retry/Re-index jobs remained queued.

The former working-directory-relative `.env` lookup could also make Uvicorn and
the worker load different settings. The absolute backend `.env` resolution
removes that ambiguity.

## Start the native development stack

Prerequisites are PostgreSQL 16, Python 3.13 with `backend/.venv` installed,
Node.js 22 with frontend dependencies installed, Docker Desktop, and native
Ollama for macOS.

Use one terminal per long-lived native process:

```shell
# Step 1: configuration
cp backend/.env.example backend/.env

# Step 2: PostgreSQL
docker compose up -d postgres

# Step 3: Qdrant and prerequisite checks
make knowledge-start

# Database schema
(cd backend && DEBUG=false .venv/bin/alembic upgrade head)

# Step 4, separate terminal: native Ollama
ollama serve
ollama pull nomic-embed-text

# Step 5: validate the exact embedding adapter
make validate-embedding

# Step 6: backend
(cd backend && DEBUG=false .venv/bin/uvicorn app.main:app --reload)

# Step 7: worker (second terminal)
(cd backend && DEBUG=false .venv/bin/python -m app.scripts.run_ingestion_worker)

# Step 8: frontend (third terminal)
(cd frontend && npm run dev)

# Step 9: start or use the existing connector from its own checkout.
# Step 10: validate one complete pipeline.
make validate-knowledge TENANT=vitwo DOCUMENT_ID=<uuid> QUERY='expected phrase'
```

The connector remains a separate repository and is not configured or modified
by this runtime work. Start it using that repository's native development
instructions after PEKA is ready.

The worker command above is the supported command. It publishes a heartbeat
immediately, logs safe startup state for the database, object store, embedding
provider, Qdrant, collection, poll interval and concurrency, continuously polls,
recovers stale locks, logs its first idle transition, and handles SIGINT/SIGTERM.
A local file lock prevents accidentally starting a duplicate worker process.

## Qdrant

`docker-compose.qdrant.yml` contains only pinned Qdrant
`qdrant/qdrant:v1.14.1`, exposes HTTP 6333 and gRPC 6334, uses the persistent
named volume `peka_qdrant_data`, and has a container health check.

```shell
docker compose -f docker-compose.qdrant.yml up -d
docker compose -f docker-compose.qdrant.yml down
docker compose -f docker-compose.qdrant.yml restart
docker compose -f docker-compose.qdrant.yml ps
docker compose -f docker-compose.qdrant.yml logs -f qdrant
curl --fail http://localhost:6333/healthz
curl --fail http://localhost:6333/collections
```

At backend startup PEKA checks Qdrant, creates the configured collection,
verifies its dimension, creates the required keyword payload indexes, and logs
the active collection. Qdrant failure never prevents tenant management,
authentication, connector APIs, or the core `/health` endpoint from starting.
Qdrant and embeddings are separate dependencies: Qdrant stores/searches
vectors, while Ollama generates them. Qdrant can therefore be healthy while
documents remain unindexed because the embedding endpoint or worker is absent.

Inspect the configured collection:

```shell
curl --fail http://localhost:6333/collections/peka_document_chunks
```

## Native Ollama on macOS

Install Ollama outside PEKA, then run:

```shell
ollama serve
ollama pull nomic-embed-text
curl --fail http://localhost:11434/api/tags
curl --fail http://localhost:11434/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"nomic-embed-text","input":["PEKA embedding validation"]}'
```

Validate through PEKA without printing a key or full provider response:

```shell
make validate-embedding
# or
cd backend && DEBUG=false .venv/bin/python -m app.scripts.validate_embedding_runtime
```

The command reports provider, safe base URL, model, configured dimension and
`healthy`, `unavailable`, or `not_configured`. It generates one embedding and
checks its dimension. Fake embeddings are restricted to `ENVIRONMENT=test`.

## Operate and diagnose

```shell
make knowledge-status
make knowledge-logs
make knowledge-restart
make knowledge-stop
```

`make knowledge-status` shows the Qdrant container, validates the configured
embedding and Qdrant providers, reports database/object-store/worker state and
queued jobs, and queries `/health/knowledge` when Uvicorn is reachable.

`GET /health/knowledge` reports independently:

- PostgreSQL and object storage;
- worker state, exact last heartbeat, age, queued jobs and stale jobs;
- embedding provider, safe base URL, model and dimension;
- Qdrant collection and point count;
- parser availability, overall state, and safe reasons.

States are `healthy`, `degraded`, `unavailable`, and `not_configured`. Provider
errors never include credentials or raw response bodies.

Inspect the latest worker heartbeat and queued jobs directly:

```shell
docker exec peka-saas-postgres psql -U peka -d peka_saas -c \
  "SELECT worker_id,status,last_seen_at,current_job_id FROM ingestion_worker_heartbeats ORDER BY last_seen_at DESC LIMIT 1"
docker exec peka-saas-postgres psql -U peka -d peka_saas -c \
  "SELECT state,count(*) FROM ingestion_jobs GROUP BY state ORDER BY state"
```

## Retry, Re-index, and visible states

The UI distinguishes `Queued`, `Parsing`, `Chunking`, `Embedding`, `Indexing`,
`Indexed`, `Blocked: embedding not configured`,
`Blocked: embedding unavailable`, `Blocked: Qdrant unavailable`, `Failed`, and
`Deleted`. Worker health is separate from document processing state.

The stored/presentation terms have distinct meanings:

- `RECEIVED`: the source object and version were accepted, not that a worker is
  actively processing them.
- `Queued`: an active job is waiting for a worker or retry time.
- `Pending`: a UI/provider result has not completed; it is not an active stage.
- `CHUNKED`: durable reusable chunks exist but are not necessarily embedded.
- `NOT_CONFIGURED`: embedding stopped safely because no real provider existed.
- `INDEXED`: current-version chunks were embedded and replaced in Qdrant.

Retry resumes from durable work where safe: existing chunks go directly to
embedding/indexing, and existing parsed sections go directly to chunking.
Re-index uses current chunks when available. Neither operation resets the
document to `RECEIVED` merely because a job was queued. Only one active job is
returned for a version, preventing Retry/Re-index duplication.

Point IDs are deterministic per version and chunk. Indexing first deletes the
document's existing tenant-filtered points and then upserts the current version,
so Re-index cannot accumulate duplicates. Superseded versions are excluded and
document deletion removes tenant-filtered points from Qdrant.

Without embeddings, processing safely stops at `CHUNKED` with
`NOT_CONFIGURED`; parsed sections and chunks remain reusable. Transient
embedding and Qdrant failures remain retryable with configured exponential
backoff and a safe blocking reason.

## Validate a document end to end

```shell
make validate-knowledge \
  TENANT=vitwo \
  DOCUMENT_ID=00000000-0000-0000-0000-000000000000 \
  QUERY='phrase expected in the document'
```

This tenant-scoped diagnostic verifies the document and current version,
stored object, parsed sections, chunks, embedding provenance, exact current
Qdrant point count, and Knowledge Service retrieval. The tenant-admin HTTP
equivalent is:

`GET /api/v1/tenant/documents/{document_id}/pipeline-validation?query=...`

If a document stays Queued, check `make knowledge-status`, then start the
worker. If it is blocked, fix the displayed embedding or Qdrant prerequisite
and press Retry. A dimension mismatch requires using a collection created for
the configured embedding dimension (or intentionally rebuilding the derived
collection); never change dimensions against an existing collection silently.

After Ollama downtime, restart `ollama serve`, validate embeddings, and press
Retry; durable chunks are reused. After Qdrant downtime, run
`make knowledge-restart`, wait for a healthy collection, and press Retry or
Re-index. These operations preserve document/version history.

## Troubleshooting

| Symptom | Checks |
|---|---|
| `Knowledge services started in degraded mode` | Check embedding variables, Qdrant configuration/health, and worker heartbeat. |
| Document remains `RECEIVED` or Pending | Check worker process, queued job, stale lock, and database configuration. |
| Chunks exist but document is not indexed | Check embedding provider, Qdrant, and the failed `EMBED_AND_INDEX` job. |
| Qdrant has points but an old document is not searchable | Check current version, deleted state, tenant filters, and embedding-model collection. |
| Retry was accepted but nothing happens | Check the worker process and heartbeat; the backend does not execute jobs. |

Production still requires managed shared object storage, authenticated TLS
Qdrant, secret injection, supervised workers, backups, retention controls, and
alerts. OCR, unsupported legacy formats, conversational AI, agents, and routing
are outside this milestone.
