# ADR-0009: Document ingestion and retrieval

Status: Accepted

## Context

PEKA connectors must deliver customer files without moving parsing or retrieval responsibilities into the appliance. Upload retries, tenant isolation, binary durability, parser failures, and a rebuildable semantic index require separate explicit boundaries.

## Decision

The flow is:

```text
Connector
  → Document API
  → Document Service
  → Object Storage + PostgreSQL
  → Ingestion Worker
  → Parser
  → Chunker
  → Embedding Provider
  → Qdrant
  → Knowledge Service
  → Tenant Search
  → Future AI Router
```

PostgreSQL and object storage are the system of record. Qdrant is a rebuildable derived index. Connector credentials determine both connector and tenant; routing headers and request metadata never select ownership.

Objects are keyed server-side by tenant/connector/document/version. The local provider uses same-directory temporary files, `fsync`, and atomic rename. An S3-compatible provider can implement the same interface later. Production must explicitly configure embedding and Qdrant providers; deterministic fake embeddings are restricted to tests.

The backend probes Qdrant during startup, creates the configured collection,
and verifies the vector dimension and mandatory payload indexes. Initialization
is non-fatal: a Qdrant failure degrades knowledge features without preventing
authentication, tenant management, connector registration, or document
receipt. The separately supervised worker polls PostgreSQL continuously. With
no embedding provider, it preserves a version at `CHUNKED` with
`NOT_CONFIGURED` rather than treating successful parsing and chunking as a
failed document.

Jobs are claimed with PostgreSQL row locks using `SKIP LOCKED`. Stages are `PARSE_DOCUMENT`, `CHUNK_DOCUMENT`, `EMBED_AND_INDEX`, `DELETE_FROM_INDEX`, and `REINDEX_DOCUMENT`; unique active-stage constraints prevent duplicates. Stale locks recover, failures use bounded exponential retry with jitter, and worker heartbeats expose diagnostics. Version statuses are validated across `RECEIVED`, `PARSING`, `PARSED`, `CHUNKING`, `CHUNKED`, `EMBEDDING`, `INDEXING`, `INDEXED`, `FAILED`, `DELETE_PENDING`, and `DELETED_FROM_INDEX`.

Parser support is:

| Format | Parser | Citation metadata |
|---|---|---|
| TXT/Markdown | UTF-8 text | Section |
| CSV | Python CSV with BOM/UTF-8/UTF-16/Windows decoding | Row |
| PDF | pypdf | Page; likely scanned PDFs fail safely |
| DOCX | python-docx | Heading/section and table |
| XLSX | openpyxl read-only/data-only | Sheet and row |

The chunker uses deterministic structure-aware windows while retaining citation coordinates; spreadsheet chunks group rows and repeat headers. Every Qdrant payload includes tenant, connector, source, document, version, chunk, filename, content hash, parser/chunker/embedding versions, lifecycle, and citation coordinates as `page`, `sheet`, and `rows` plus the existing typed fields. Point UUIDs are deterministic for version plus chunk index. Before upsert the worker removes points for that tenant/document so the new current version replaces old active points; deletion removes all tenant/document points. Knowledge Service injects tenant equality and verifies every hit against PostgreSQL active state.

## Consequences

- API latency covers durable receipt, not parsing or indexing.
- Restarted workers resume PostgreSQL jobs; exact connector retries are idempotent.
- Qdrant loss is recoverable by re-enqueuing current stored versions.
- Superseded versions remain auditable in PostgreSQL/object storage. Only the current version should be re-indexed during a full rebuild.
- The future AI layer must call Knowledge Service rather than Qdrant directly.
- OCR, images, richer spreadsheet semantics, hybrid search, storage lifecycle policies, and automated bulk re-index administration remain future work.
