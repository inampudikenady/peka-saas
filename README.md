# PEKA SaaS

Commercial multi-tenant SaaS platform for PEKA.

This repository contains the SaaS control plane responsible for:

- Tenants
- Users
- Authentication
- Connector registration
- Connector health and integration visibility
- Chat and LLM orchestration
- Authorized Connector retrieval with structured citations
- Audit logging
- Platform APIs
- Web UI

Customer documents, parsing, embeddings, and the Local Knowledge Store live in
the PEKA Connector repository and customer environment.

## Connector management

PEKA SaaS implements the connector control-plane lifecycle:

- Tenant administrators generate 30-minute, single-use registration tokens under `/api/v1/tenant/connectors/registration-tokens`.
- Appliances register through `POST /api/v1/connectors/register` and receive a connector ID and one-time connector secret.
- Appliances report health through `POST /api/v1/connectors/{connector_id}/heartbeat` every 300 seconds.
- Tenant users see only their tenant's inventory. Platform administrators and platform read-only users have cross-tenant read-only inventory.
- Status is derived by SaaS and refreshed by heartbeats, reads, and a background maintenance loop.

Raw registration tokens and connector secrets are never stored. See [Connector API](docs/api/connectors.md), [security](docs/security/connectors.md), and [database design](docs/database/connectors.md).

## Local Knowledge Store boundary

SaaS sends an authorized `knowledge_search` request through the existing
connector channel. The Connector embeds and searches locally, applies tenant and
document authorization, and returns only the minimum relevant context needed by
chat. Heartbeats contain status and aggregate counts only—never document names,
bodies, chunks, embeddings, or vector payloads.

Historical SaaS document tables, object storage, and Qdrant volumes are retained
for controlled export, validation, and rollback. They are not initialized by the
normal SaaS runtime and receive no new writes. See
[the migration notes](docs/architecture/0010-customer-resident-knowledge-store.md).

## Native development

The backend and frontend are supported as native processes. This repository
does not provide a Docker deployment for either application.

```shell
# Configure backend/.env, then start PostgreSQL and the selected chat provider.
(cd backend && .venv/bin/alembic upgrade head)
(cd backend && .venv/bin/uvicorn app.main:app --reload)

# In another terminal:
(cd frontend && npm run dev)
```

The frontend defaults to `http://127.0.0.1:8000` for its backend. Override
`PEKA_BACKEND_URL` with an explicit native or deployed API URL when required.

## Official PEKA CLI

The production-oriented CLI is owned by this repository and manages only the
PEKA application and Platform administration. The helper scripts in the parent
development workspace remain separate and are not runtime dependencies.

For a fresh checkout:

```shell
git clone <repository>
cd peka-saas
cp backend/.env.example backend/.env
# Configure backend/.env and make PostgreSQL available.

./cli/peka install
(cd backend && .venv/bin/alembic upgrade head)
./cli/peka doctor
./cli/peka app start
```

The main commands are:

```text
peka app <start|stop|restart|status|logs>
peka admin reset-password <username>
peka install
peka doctor
peka help [command]
peka --version
```

`peka install` creates `backend/.venv`; no activated or copied virtual
environment is expected. Runtime PID files and logs live in `.runtime/`.

To make `peka` available on your user PATH without moving the repository, use a
symbolic link (the CLI resolves the real script location):

```shell
mkdir -p "$HOME/.local/bin"
ln -s "$(pwd)/cli/peka" "$HOME/.local/bin/peka"
```

Generate a normal one-time Platform Admin reset link with:

```shell
peka admin reset-password <username>
```

The CLI uses the same reset-token service as the Platform Users UI. It does not
accept a new password or modify password hashes directly.

View the Unix manual locally:

```shell
man ./docs/man/peka.1
```

To install the page for only the current user:

```shell
mkdir -p "$HOME/.local/share/man/man1"
cp docs/man/peka.1 "$HOME/.local/share/man/man1/peka.1"
man peka
```

## Verification

```shell
cd backend && DEBUG=false .venv/bin/pytest -q
cd frontend && npm test && npm run lint && npm run build
```

Docker is optional for disposable test dependencies. Historical document-plane
tests may still start an isolated Qdrant using migration-only configuration; this
is not a production SaaS dependency.

```shell
./scripts/run-disposable-container-tests.sh
```

The normal SaaS runtime has no embedding or Qdrant configuration. Configure those
components on PEKA Connector v1.0.0.
