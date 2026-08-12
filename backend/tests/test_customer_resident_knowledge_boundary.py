from pathlib import Path

from app.main import app


def test_normal_saas_routes_and_compose_have_no_document_plane() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/v1/tenant/documents" not in paths
    assert not any(
        path.startswith("/api/v1/connectors/") and "/documents" in path
        for path in paths
    )
    assert "/health/knowledge" not in paths

    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    assert "  qdrant:" not in compose
    assert "  ingestion-worker:" not in compose
    assert "PEKA_QDRANT_URL" not in compose


def test_chat_retrieval_boundary_is_connector_owned() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "api"
        / "routes"
        / "tenant"
        / "ai_answer.py"
    ).read_text()
    assert "ConnectorKnowledgeService(db)" in source
    assert "DocumentRepository" not in source
