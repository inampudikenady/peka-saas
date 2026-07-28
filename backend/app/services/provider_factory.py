"""Validated construction of optional ingestion providers."""

from app.core.config import Settings, settings
from app.services.embedding_provider import (
    DeterministicFakeEmbeddingProvider,
    DisabledEmbeddingProvider,
    EmbeddingProvider,
    EmbeddingProviderNotConfigured,
    OpenAICompatibleEmbeddingProvider,
)
from app.services.object_storage import LocalFilesystemObjectStorage, ObjectStorage
from app.services.vector_store import (
    DisabledVectorStore, InMemoryVectorStore, QdrantVectorStore, VectorStore,
)
from app.services.llm_provider import (
    DeterministicFakeLLMProvider,
    DisabledLLMProvider,
    LLMProvider,
    LLMProviderNotConfigured,
    OpenAICompatibleLLMProvider,
)


_test_vectors = InMemoryVectorStore()


def object_storage(config: Settings = settings) -> ObjectStorage:
    if config.peka_object_storage_backend == "local":
        return LocalFilesystemObjectStorage(config.peka_object_storage_local_root)
    raise RuntimeError(f"Unsupported object storage backend: {config.peka_object_storage_backend}")


def embedding_provider(config: Settings = settings) -> EmbeddingProvider:
    if config.peka_embedding_provider == "disabled":
        return DisabledEmbeddingProvider()
    if config.peka_embedding_provider == "fake" and config.environment.lower() == "test":
        return DeterministicFakeEmbeddingProvider(config.peka_embedding_dimension)
    if config.peka_embedding_provider == "fake":
        raise EmbeddingProviderNotConfigured(
            "Fake embeddings are restricted to the test environment"
        )
    if config.peka_embedding_provider == "openai-compatible":
        if not config.peka_embedding_base_url:
            raise EmbeddingProviderNotConfigured("Embedding URL is required")
        return OpenAICompatibleEmbeddingProvider(
            config.peka_embedding_base_url, config.peka_embedding_api_key,
            config.peka_embedding_model, config.peka_embedding_dimension,
            config.peka_embedding_timeout_seconds, config.peka_embedding_batch_size,
        )
    raise EmbeddingProviderNotConfigured("Document embedding provider is unsupported")


def vector_store(config: Settings = settings) -> VectorStore:
    if config.peka_qdrant_url:
        return QdrantVectorStore(
            config.peka_qdrant_url, config.peka_qdrant_collection,
            config.peka_qdrant_api_key, config.peka_qdrant_timeout_seconds,
            config.peka_qdrant_tls_verify,
        )
    if config.environment.lower() == "test":
        return _test_vectors
    return DisabledVectorStore()


def chat_provider(config: Settings = settings) -> LLMProvider:
    if config.peka_chat_provider == "disabled":
        return DisabledLLMProvider()
    if config.peka_chat_provider == "fake" and config.environment.lower() == "test":
        return DeterministicFakeLLMProvider()
    if config.peka_chat_provider == "fake":
        raise LLMProviderNotConfigured(
            "Fake chat providers are restricted to the test environment"
        )
    if config.peka_chat_provider == "openai-compatible":
        if not config.peka_chat_base_url:
            raise LLMProviderNotConfigured("Chat provider URL is required")
        return OpenAICompatibleLLMProvider(
            config.peka_chat_base_url,
            config.peka_chat_api_key,
            config.peka_chat_model,
            embedding_model=config.peka_embedding_model,
            embedding_dimension=config.peka_embedding_dimension,
            timeout_seconds=config.peka_chat_timeout_seconds,
            streaming_enabled=config.peka_chat_streaming_enabled,
        )
    raise LLMProviderNotConfigured("Chat provider is unsupported")
