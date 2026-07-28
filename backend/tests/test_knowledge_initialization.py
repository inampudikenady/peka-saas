from app.core.config import Settings
from app.services.knowledge_initialization import initialize_knowledge_dependencies


class StubVectors:
    def __init__(self, healthy: bool = True, fail_ensure: bool = False) -> None:
        self.healthy = healthy
        self.fail_ensure = fail_ensure
        self.ensured_dimension = None

    def health_check(self):
        return self.healthy

    def ensure_collection(self, dimension):
        self.ensured_dimension = dimension
        if self.fail_ensure:
            raise RuntimeError("unavailable detail")


def test_qdrant_startup_initialization_verifies_collection(monkeypatch):
    vectors = StubVectors()
    monkeypatch.setattr(
        "app.services.knowledge_initialization.vector_store",
        lambda _config: vectors,
    )
    config = Settings(
        debug=False,
        peka_qdrant_url="http://qdrant:6333",
        peka_embedding_dimension=384,
    )
    result = initialize_knowledge_dependencies(config)
    assert result.status == "healthy"
    assert result.collection_ready is True
    assert vectors.ensured_dimension == 384


def test_qdrant_unavailable_never_raises_during_startup(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge_initialization.vector_store",
        lambda _config: StubVectors(healthy=False),
    )
    config = Settings(debug=False, peka_qdrant_url="http://unavailable:6333")
    result = initialize_knowledge_dependencies(config)
    assert result.status == "degraded"
    assert result.qdrant_configured is True
    assert result.collection_ready is False


def test_qdrant_not_configured_is_degraded_but_safe():
    result = initialize_knowledge_dependencies(
        Settings(debug=False, peka_qdrant_url=None)
    )
    assert result.status == "degraded"
    assert result.qdrant_configured is False
