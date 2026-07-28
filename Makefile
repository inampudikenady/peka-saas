.PHONY: knowledge-start knowledge-stop knowledge-restart knowledge-status knowledge-logs worker validate-embedding validate-knowledge

knowledge-start:
	docker compose -f docker-compose.qdrant.yml up -d
	@curl --fail --silent --show-error http://localhost:6333/healthz >/dev/null && echo "Qdrant: healthy" || (echo "Qdrant: unavailable"; exit 1)
	@curl --fail --silent http://localhost:11434/api/tags | grep -q '"nomic-embed-text' && echo "Ollama: healthy; nomic-embed-text available" || echo "Ollama: unavailable or nomic-embed-text is not pulled"
	@echo "Backend: cd backend && .venv/bin/uvicorn app.main:app --reload"
	@echo "Worker:  cd backend && .venv/bin/python -m app.scripts.run_ingestion_worker"

knowledge-stop:
	docker compose -f docker-compose.qdrant.yml down

knowledge-restart:
	docker compose -f docker-compose.qdrant.yml restart

knowledge-status:
	@docker compose -f docker-compose.qdrant.yml ps
	@cd backend && DEBUG=false .venv/bin/python -m app.scripts.knowledge_status
	@curl --fail --silent http://127.0.0.1:8000/health/knowledge || echo "Backend knowledge endpoint: unavailable"

knowledge-logs:
	docker compose -f docker-compose.qdrant.yml logs -f qdrant

worker:
	cd backend && DEBUG=false .venv/bin/python -m app.scripts.run_ingestion_worker

validate-embedding:
	cd backend && DEBUG=false .venv/bin/python -m app.scripts.validate_embedding_runtime

validate-knowledge:
	@test -n "$(TENANT)" -a -n "$(DOCUMENT_ID)" -a -n "$(QUERY)" || (echo "Usage: make validate-knowledge TENANT=vitwo DOCUMENT_ID=<uuid> QUERY='expected phrase'"; exit 2)
	cd backend && DEBUG=false .venv/bin/python -m app.scripts.validate_knowledge_pipeline --tenant "$(TENANT)" --document-id "$(DOCUMENT_ID)" --query "$(QUERY)"
