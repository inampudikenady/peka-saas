#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_file="${repository_root}/infra/testing/compose.test.yml"
project_name="peka-saas-test-${PPID}-$$"
test_object_root="$(mktemp -d "${TMPDIR:-/tmp}/peka-saas-test.XXXXXX")"

export PEKA_TEST_POSTGRES_PORT="${PEKA_TEST_POSTGRES_PORT:-55432}"
export PEKA_TEST_QDRANT_HTTP_PORT="${PEKA_TEST_QDRANT_HTTP_PORT:-56333}"
export PEKA_TEST_QDRANT_GRPC_PORT="${PEKA_TEST_QDRANT_GRPC_PORT:-56334}"

cleanup() {
  docker compose -p "${project_name}" -f "${compose_file}" down \
    --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "${test_object_root}"
}
trap cleanup EXIT INT TERM

docker compose -p "${project_name}" -f "${compose_file}" up -d --wait

export ENVIRONMENT=test
export DEBUG=false
export DATABASE_URL="postgresql+psycopg://peka_test:peka_test@127.0.0.1:${PEKA_TEST_POSTGRES_PORT}/peka_saas_test"
export PLATFORM_ADMIN_JWT_SECRET=disposable-container-test-only
export TENANT_SSO_ENCRYPTION_KEY=disposable-container-test-encryption-key
export PEKA_OBJECT_STORAGE_BACKEND=local
export PEKA_OBJECT_STORAGE_LOCAL_ROOT="${test_object_root}"
export PEKA_QDRANT_URL="http://127.0.0.1:${PEKA_TEST_QDRANT_HTTP_PORT}"
export PEKA_QDRANT_COLLECTION=peka_test_document_chunks
export PEKA_QDRANT_API_KEY=
export PEKA_EMBEDDING_PROVIDER=fake
export PEKA_CHAT_PROVIDER=disabled

(
  cd "${repository_root}/backend"
  .venv/bin/alembic upgrade head
  .venv/bin/pytest -q
)

(
  cd "${repository_root}/frontend"
  npm test
  npm run lint
)
