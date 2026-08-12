# Testing

PEKA backend and frontend tests normally run with the native Python and Node.js
toolchains:

```shell
cd backend && DEBUG=false .venv/bin/pytest -q
cd frontend && npm test && npm run lint && npm run build
```

Docker is optional and is not an application runtime. The repository retains
one Compose file solely for disposable PostgreSQL and Qdrant test dependencies:
`infra/testing/compose.test.yml`. It contains no backend, frontend, worker, or
production service.

Run the isolated container-assisted suite with:

```shell
./scripts/run-disposable-container-tests.sh
```

The runner:

- creates a unique Compose project;
- uses test-only database credentials, ports, collection names, and object paths;
- passes all test configuration through process environment variables;
- runs migrations and backend/frontend tests with native project toolchains;
- stores PostgreSQL and Qdrant data only in container `tmpfs`; and
- traps normal exit, failure, and interruption to run `down --volumes
  --remove-orphans` and delete the temporary object directory.

The default test ports are PostgreSQL `55432`, Qdrant HTTP `56333`, and Qdrant
gRPC `56334`. CI may override `PEKA_TEST_POSTGRES_PORT`,
`PEKA_TEST_QDRANT_HTTP_PORT`, and `PEKA_TEST_QDRANT_GRPC_PORT`. These variables
are consumed only by the disposable test runner and Compose file; they do not
change normal development or production configuration.
