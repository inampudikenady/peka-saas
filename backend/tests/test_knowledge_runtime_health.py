import json
from pathlib import Path

from app.core.config import BACKEND_ENV_FILE, Settings
from app.services.knowledge_runtime_health import embedding_health, qdrant_health


def test_all_processes_use_the_backend_environment_file():
    assert BACKEND_ENV_FILE == Path(__file__).resolve().parents[1] / ".env"
    assert Settings.model_config["env_file"] == BACKEND_ENV_FILE


def test_absent_embedding_and_qdrant_are_not_configured():
    config = Settings(
        debug=False,
        peka_embedding_provider="disabled",
        peka_qdrant_url=None,
    )
    assert embedding_health(config)["status"] == "not_configured"
    assert qdrant_health(config)["status"] == "not_configured"


def test_embedding_unreachable_is_safe(monkeypatch):
    class Unreachable:
        name = "openai-compatible"
        model = "nomic-embed-text"
        dimension = 768

        def embed(self, _texts):
            raise RuntimeError("raw private provider response")

    monkeypatch.setattr(
        "app.services.knowledge_runtime_health.embedding_provider",
        lambda _config: Unreachable(),
    )
    config = Settings(
        debug=False,
        peka_embedding_provider="openai-compatible",
        peka_embedding_base_url="http://localhost:11434/v1",
        peka_embedding_api_key="must-never-appear",
        peka_embedding_model="nomic-embed-text",
        peka_embedding_dimension=768,
    )
    serialized = json.dumps(embedding_health(config))
    assert '"status": "unavailable"' in serialized
    assert "must-never-appear" not in serialized
    assert "raw private provider response" not in serialized


def test_embedding_dimension_mismatch_is_degraded(monkeypatch):
    class WrongDimension:
        name = "openai-compatible"
        model = "nomic-embed-text"
        dimension = 768

        def embed(self, _texts):
            return [[0.0] * 10]

    monkeypatch.setattr(
        "app.services.knowledge_runtime_health.embedding_provider",
        lambda _config: WrongDimension(),
    )
    result = embedding_health(
        Settings(
            debug=False,
            peka_embedding_provider="openai-compatible",
            peka_embedding_base_url="http://localhost:11434/v1",
            peka_embedding_dimension=768,
        )
    )
    assert result["status"] == "degraded"
    assert result["actual_dimension"] == 10


def test_unreachable_qdrant_is_safe(monkeypatch):
    class Unreachable:
        def health_check(self):
            return False

    monkeypatch.setattr(
        "app.services.knowledge_runtime_health.vector_store",
        lambda _config: Unreachable(),
    )
    result = qdrant_health(
        Settings(debug=False, peka_qdrant_url="http://localhost:6333")
    )
    assert result["status"] == "unavailable"
    assert "localhost" not in str(result["reason"])
