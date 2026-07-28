# Private AI conversations

AI conversation routes are tenant-user routes under
`/api/v1/tenant/ai/conversations`. Tenant identity comes from the resolved
tenant URL and user identity comes from the authenticated tenant session.
Neither value is accepted from the request body.

Every repository read and mutation is constrained by both `tenant_id` and
`user_id`. An out-of-scope conversation returns `404`, including requests from
another user, a tenant administrator, or a user in another tenant. There is no
platform conversation-content API.

## Endpoints

- `POST /tenant/ai/conversations` creates an empty private conversation.
- `GET /tenant/ai/conversations` lists owned conversations with `limit`,
  `offset`, and optional `archived` filtering.
- `GET /tenant/ai/conversations/{id}` returns the owned conversation and its
  stored messages.
- `GET /tenant/ai/conversations/{conversation_id}/messages/{message_id}/citations/{citation_id}`
  returns the immutable, owner-scoped evidence snapshot stored with an answer.
- `PATCH /tenant/ai/conversations/{id}/title` renames it.
- `PATCH /tenant/ai/conversations/{id}/archive` archives or restores it.
- `DELETE /tenant/ai/conversations/{id}` soft-deletes it.
- `POST /tenant/ai/answer/stream` creates or continues a conversation when the
  optional `conversation_id` is supplied.

The user message and a `streaming` assistant placeholder are committed before
generation. Successful answers are stored atomically with citations, immutable
document version and chunk identifiers, retrieval summary, model, and prompt
version. Failure and cancellation store only safe error codes. On cancellation,
only answer text already emitted through SSE is retained. Streaming records
older than 15 minutes are marked failed when the owner next accesses AI
history, preventing handled interruptions from remaining indefinitely active.
A partial unique database index and service-level ownership check reject a
second active generation in the same conversation with `409`.

For follow-up questions, recent completed owned messages are passed as bounded
conversation context. Message count and token limits are configurable with
`PEKA_AI_MAX_PRIOR_MESSAGES` and `PEKA_AI_MAX_HISTORY_TOKENS`. Old citation
labels are removed and the prompt marks prior turns as non-evidence; every new
answer must still cite only newly retrieved tenant evidence. Each assistant
message stores the IDs of the exact context messages used for generation.

Stored answers are historical records of the evidence version used at
generation time. Citation snapshots include the redacted excerpt, source
metadata, revision, ingestion timestamp, and retrieval score. They are not
regenerated or fetched from the live document when reopened and must not be
presented as reflecting the latest document revision.

Secret detection is applied before retrieval and prompting and again before
answer, citation, and conversation persistence. Redaction events log only safe
identifiers, categories, and counts; detected values are never logged.

## Retention

Deletion is currently soft deletion. A permanent-deletion schedule, retention
duration, legal-hold behavior, user export, and organization-wide surveillance
are deliberately not defined by this implementation and require explicit
product and privacy policy decisions.
