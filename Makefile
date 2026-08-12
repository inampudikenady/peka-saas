.PHONY: native-help migrate backend frontend knowledge-status worker validate-embedding validate-knowledge test-containers

native-help:
	@echo "PostgreSQL and the chat provider must be available through backend/.env."
	@echo "Migrate:  make migrate"
	@echo "Backend:  make backend"
	@echo "Frontend: make frontend"

migrate:
	cd backend && DEBUG=false .venv/bin/alembic upgrade head

backend:
	cd backend && DEBUG=false .venv/bin/uvicorn app.main:app --reload

frontend:
	cd frontend && npm run dev

knowledge-status: # migration-only legacy document-plane diagnostic
	@cd backend && DEBUG=false .venv/bin/python -m app.scripts.knowledge_status
	@curl --fail --silent http://127.0.0.1:8000/health/knowledge || echo "Backend knowledge endpoint: unavailable"

worker: # migration-only legacy document-plane worker; never part of normal SaaS startup
	cd backend && DEBUG=false .venv/bin/python -m app.scripts.run_ingestion_worker

validate-embedding: # migration-only
	cd backend && DEBUG=false .venv/bin/python -m app.scripts.validate_embedding_runtime

validate-knowledge: # migration-only
	@test -n "$(TENANT)" -a -n "$(DOCUMENT_ID)" -a -n "$(QUERY)" || (echo "Usage: make validate-knowledge TENANT=vitwo DOCUMENT_ID=<uuid> QUERY='expected phrase'"; exit 2)
	cd backend && DEBUG=false .venv/bin/python -m app.scripts.validate_knowledge_pipeline --tenant "$(TENANT)" --document-id "$(DOCUMENT_ID)" --query "$(QUERY)"

test-containers:
	./scripts/run-disposable-container-tests.sh
