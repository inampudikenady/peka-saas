# Local AI Answer Development

PEKA uses native Ollama on macOS for chat and embeddings. Do not create an
Ollama Docker service for this runtime.

## Required services

Start the existing local development stack in separate terminals:

1. PostgreSQL using the project's existing local configuration.
2. Qdrant:

   ```bash
   docker compose -f docker-compose.qdrant.yml up -d
   ```

3. Native Ollama (installed outside this repository):

   ```bash
   ollama serve
   ```

4. Backend:

   ```bash
   cd backend
   source .venv/bin/activate
   uvicorn app.main:app --reload
   ```

5. Frontend:

   ```bash
   cd frontend
   npm run dev
   ```

FastAPI starts the ingestion runtime in-process; no worker terminal is required.

The connector continues to run from its own repository and is not modified by
the AI Answer Service.

## Configuration

Copy values from `backend/.env.example` into the existing absolute
`backend/.env`. The validated native runtime is:

```dotenv
PEKA_EMBEDDING_PROVIDER=openai-compatible
PEKA_EMBEDDING_BASE_URL=http://localhost:11434/v1
PEKA_EMBEDDING_MODEL=nomic-embed-text
PEKA_EMBEDDING_DIMENSION=768

PEKA_CHAT_PROVIDER=openai-compatible
PEKA_CHAT_BASE_URL=http://localhost:11434/v1
PEKA_CHAT_MODEL=qwen3:8b
PEKA_CHAT_STREAMING_ENABLED=true
```

`PEKA_CHAT_API_KEY` and `PEKA_EMBEDDING_API_KEY` may remain empty for a local
Ollama endpoint. Never place real credentials in source control.

The chat provider is independent of the ingestion embedding provider.
Disabling or losing chat leaves tenant administration, document ingestion, and
retrieval operational.

## Runtime checks

Confirm the native process and required models without installing or changing
models:

```bash
ollama ps
curl -fsS http://localhost:11434/api/tags
curl -fsS http://localhost:6333/readyz
curl -fsS http://localhost:8000/health/knowledge
```

The health response reports independent `ingestion_state`, `retrieval_state`,
and `chat_state` values. Chat diagnostics expose the provider name, model,
redacted base URL, cached connectivity state, streaming support, context window,
and output limit. They never expose credentials or provider response bodies.

## API smoke tests

Use an authenticated tenant session:

```bash
curl -N \
  -H 'Content-Type: application/json' \
  -b cookies.txt \
  --data '{"query":"How do I install vManager?","top_k":8}' \
  http://localhost:8000/t/vitwo/api/v1/tenant/ai/answer/stream
```

For the synchronous path, use `/answer` without `-N`.

Validate at least:

- vManager installation,
- a Ventana runbook summary,
- Roche infrastructure details,
- an unsupported question,
- a prompt-injection-style request,
- a tenant-owned filter and a cross-tenant filter.

A grounded result must contain only citation IDs supplied by the service.
Unsupported questions must return `INSUFFICIENT_EVIDENCE` without a model
summary. Neither response nor logs may contain hidden reasoning.

## Quality commands

From `backend`:

```bash
pytest
ruff check app tests
mypy --strict app
alembic current
alembic check
```

From `frontend`:

```bash
npm test -- --run
npm run lint
npx tsc --noEmit
npm run build
```

From the repository root:

```bash
docker compose -f docker-compose.qdrant.yml config
git diff --check
```

## Operational behavior

- Retrieved document text is untrusted evidence and is never executed as
  instructions.
- Provider reasoning fields are discarded, reasoning mode is disabled when
  supported (`reasoning_effort=none` on Ollama's OpenAI-compatible endpoint),
  and tagged reasoning is stripped as defense in depth.
- Provider output is buffered until citation validation before SSE answer
  tokens are released.
- Prompts, questions, retrieved text, generated answers, and credentials are not
  written to application logs.
- The service is stateless; refreshing the page discards the current answer.
## Operational Assistant routing

Obvious inventory and resource questions use deterministic routing before
document retrieval. SaaS creates a short-lived, tenant-scoped operational tool
request. A registered connector polls the existing outbound connector API,
claims one request, executes one of the allow-listed structured operations, and
posts a structured result. SaaS does not store an inventory projection and
does not call connectors directly.

The initial allow list is:

- `get_inventory_summary`
- `count_assets`
- `search_assets`
- `get_asset_details`
- `get_asset_status`
- `get_asset_utilization`

Claims and requests expire. Connector results are accepted only from the
connector assigned to the request. Resource utilization uses fixed,
parameterized node-exporter queries; callers cannot supply PromQL.
