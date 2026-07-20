# PEKA SaaS

Commercial multi-tenant SaaS platform for PEKA.

This repository contains the SaaS control plane responsible for:

- Tenants
- Users
- Authentication
- Connector registration
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

## Local verification

```shell
cd backend && DEBUG=false .venv/bin/pytest -q
cd frontend && npm test && npm run lint && npm run build
docker compose build
```
