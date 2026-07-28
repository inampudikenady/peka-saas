# AI Answer API

The AI Answer API provides grounded answers in new or existing private
conversations owned by the authenticated tenant user. It never accepts a
tenant or user identifier from the client. Retrieval is performed only through
Knowledge Service.

## Authentication and tenant context

Both endpoints require the existing tenant-user session or bearer
authentication and tenant routing context:

```text
POST /api/v1/tenant/ai/answer
POST /api/v1/tenant/ai/answer/stream
```

When using path-based tenant development routing, the equivalent URL is:

```text
/t/{tenant_slug}/api/v1/tenant/ai/answer
```

The server derives `tenant_id` from authenticated context. Supplying
`tenant_id` or another unknown field is rejected.

## Request

```json
{
  "query": "How do I install vManager?",
  "conversation_id": null,
  "top_k": 8,
  "filters": {
    "connector_ids": [],
    "document_ids": [],
    "source_types": []
  }
}
```

- `query` is required, non-blank, and bounded by server configuration.
- `conversation_id` is optional and may identify only a conversation owned by
  the authenticated user in the current tenant.
- `top_k` is optional and bounded by server configuration.
- filter identifiers must belong to the authenticated tenant.
- omitting `filters` searches all eligible indexed knowledge for the tenant.

## Synchronous response

```json
{
  "answer": "Install the required components and complete the documented setup steps. [C1]",
  "grounded": true,
  "code": null,
  "citations": [
    {
      "citation_id": "C1",
      "source_type": "document",
      "document_id": "9ac727a7-7038-4bed-a1cc-b9cab87001f8",
      "version_id": "4ba84d50-1739-46d9-970c-d01b257b04ef",
      "chunk_id": "2cc67f41-d605-4d39-a495-cbf643704b0a",
      "title": "vManager Installation and Configuration",
      "page_number": 12,
      "section_title": "Installation",
      "sheet_name": null,
      "row_start": null,
      "row_end": null,
      "score": 0.82,
      "excerpt": "Install the signed package from the approved repository.",
      "document_type": "application/pdf",
      "source_system": "vCenter",
      "source_id": "opaque-source-id",
      "ingested_at": "2026-01-01T12:00:00Z",
      "revision": "sha256:...",
      "sensitive_content_redacted": false,
      "redaction_categories": []
    }
  ],
  "retrieval": {
    "result_count": 8,
    "included_count": 6,
    "top_k": 8
  },
  "model": {
    "provider": "openai-compatible",
    "model": "qwen3:8b"
  },
  "request_id": "fa3f8d48-4a44-43e4-84ed-97f72d9be7f1"
}
```

Citation object IDs are opaque references. The tenant UI displays only safe
source labels and locations. Citation excerpts are redacted before prompting,
output, and persistence. The stored evidence endpoint described in
`ai-conversations.md` returns the immutable snapshot used for that answer,
never a live re-fetch.

## Insufficient evidence

Insufficient evidence is a successful, non-generated result. The model is not
called:

```json
{
  "answer": "I could not find enough information in the available PEKA knowledge sources to answer that question.",
  "grounded": false,
  "code": "INSUFFICIENT_EVIDENCE",
  "citations": [],
  "retrieval": {
    "result_count": 0,
    "included_count": 0,
    "top_k": 8
  },
  "model": null,
  "request_id": "fa3f8d48-4a44-43e4-84ed-97f72d9be7f1"
}
```

## Errors

Errors have one safe schema:

```json
{
  "code": "CHAT_PROVIDER_UNAVAILABLE",
  "message": "The AI service is temporarily unavailable.",
  "request_id": "fa3f8d48-4a44-43e4-84ed-97f72d9be7f1"
}
```

| HTTP | Codes |
| --- | --- |
| 422 | `INVALID_QUERY`, `QUERY_TOO_LONG`, `INVALID_FILTER`, `CONTEXT_LIMIT_EXCEEDED` |
| 409 | Another response is already being generated in the conversation |
| 429 | `CHAT_PROVIDER_RATE_LIMITED` |
| 502 | `CHAT_PROVIDER_INVALID_RESPONSE`, `CITATION_VALIDATION_FAILED`, `AI_GENERATION_FAILED` |
| 503 | `KNOWLEDGE_UNAVAILABLE`, `CHAT_PROVIDER_NOT_CONFIGURED`, `CHAT_PROVIDER_UNAVAILABLE` |
| 504 | `CHAT_PROVIDER_TIMEOUT` |

Raw provider responses, credentials, prompts, retrieved text, and hidden
reasoning are never included.

Query text, bounded conversation context, retrieved evidence, model output,
stored messages, and citation snapshots pass through centralized secret
detection. Detected values are replaced with typed redaction markers. Ordinary
IP addresses, ports, UUIDs, and usernames are not treated as secrets.

## SSE stream

The streaming endpoint accepts the same request and returns
`text/event-stream`. Events are ordered:

```text
event: retrieval
data: {"result_count":8,"included_count":6,"top_k":8}

event: token
data: {"text":"Install the required components. [C1]"}

event: citations
data: {"citations":[...]}

event: complete
data: {"grounded":true,"request_id":"...","model":{"provider":"openai-compatible","model":"qwen3:8b"}}
```

An insufficient response emits `retrieval`, one safe `token`, empty
`citations`, then `complete` with `grounded:false`. A provider/domain failure
emits an `error` event with the structured error fields.

There are no reasoning, prompt, evidence, tool, action, or conversation events.
Citations are emitted only after the complete answer is validated. Disconnects
cancel the server-side stream where the transport exposes cancellation.
