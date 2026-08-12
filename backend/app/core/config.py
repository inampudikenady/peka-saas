# app/core/config.py

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "PEKA Platform"
    app_version: str = "0.1.0"
    environment: str = Field(default="local")
    debug: bool = Field(default=False)

    api_prefix: str = "/api/v1"

    tenant_url_scheme: str = "https"
    tenant_base_domain: str = "peka.com"
    tenant_url_mode: str = "subdomain"
    tenant_dev_base_url: str = "https://kenady-macbook-air.tailce91e3.ts.net"
    platform_frontend_base_url: str = "https://kenady-macbook-air.tailce91e3.ts.net"
    default_timezone: str = "UTC"
    support_contact: str | None = None
    tenant_password_reset_minutes: int = Field(default=45, ge=30, le=60)
    tenant_email_delivery_backend: str = "development_outbox"

    database_url: str = Field(
        default="postgresql+psycopg://peka:peka@localhost:5432/peka_platform"
    )

    log_level: str = Field(default="INFO")

    platform_admin_jwt_secret: str = Field(default="change-me-local-only")
    platform_admin_jwt_algorithm: str = Field(default="HS256")
    platform_admin_access_token_minutes: int = Field(default=60)
    tenant_access_token_minutes: int = Field(default=60)
    tenant_session_cookie_name: str = Field(default="peka_tenant_session")
    tenant_sso_encryption_key: str | None = Field(default=None)
    connector_maintenance_interval_seconds: int = Field(default=60, ge=10)
    connector_max_active_per_tenant: int | None = Field(default=None, ge=1)

    # Legacy document-plane settings are migration-only. The normal SaaS app does
    # not initialize, ingest, embed, or retrieve through these providers.
    peka_object_storage_backend: str = "local"
    peka_object_storage_local_root: str = "/tmp/peka-saas-documents"
    peka_s3_endpoint: str | None = None
    peka_s3_bucket: str | None = None
    peka_s3_region: str | None = None
    peka_s3_access_key: str | None = None
    peka_s3_secret_key: str | None = None
    peka_qdrant_url: str | None = None
    peka_qdrant_api_key: str | None = None
    peka_qdrant_collection: str = "peka_document_chunks"
    peka_qdrant_timeout_seconds: float = Field(default=30, ge=1)
    peka_qdrant_tls_verify: bool = True
    peka_embedding_provider: str = "disabled"
    peka_embedding_base_url: str | None = None
    peka_embedding_api_key: str | None = None
    peka_embedding_model: str = "text-embedding-3-small"
    peka_embedding_dimension: int = Field(default=1536, ge=1)
    peka_embedding_batch_size: int = Field(default=64, ge=1, le=512)
    peka_embedding_timeout_seconds: float = Field(default=30, ge=1)
    peka_ingestion_worker_enabled: bool = False
    peka_ingestion_worker_poll_seconds: float = Field(default=2.0, ge=0.1)
    # One lock-protected runtime claims one job at a time (in-process by default).
    peka_ingestion_worker_concurrency: int = Field(default=1, ge=1, le=1)
    peka_ingestion_worker_stale_job_seconds: int = Field(default=600, ge=30)
    peka_ingestion_worker_heartbeat_stale_seconds: int = Field(default=60, ge=10)
    peka_ingestion_job_max_attempts: int = Field(default=5, ge=1, le=100)
    peka_ingestion_retry_base_seconds: float = Field(default=2.0, ge=0.1)
    peka_ingestion_retry_max_seconds: float = Field(default=300.0, ge=1)
    peka_ingestion_max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    peka_document_idempotency_hours: int = Field(default=24, ge=1)

    # Stateless grounded-answer provider. Chat and embeddings are configured
    # independently even when both use the same OpenAI-compatible runtime.
    peka_chat_provider: str = "disabled"
    peka_chat_base_url: str | None = None
    peka_chat_api_key: str | None = None
    peka_chat_model: str = "qwen3:8b"
    peka_chat_timeout_seconds: float = Field(default=120, ge=1)
    peka_chat_max_output_tokens: int = Field(default=768, ge=1, le=8192)
    peka_chat_temperature: float = Field(default=0.1, ge=0, le=2)
    peka_chat_context_window: int = Field(default=4096, ge=1024)
    peka_chat_streaming_enabled: bool = True
    peka_chat_health_cache_seconds: int = Field(default=60, ge=10)
    peka_ai_min_retrieval_score: float = Field(default=0.60, ge=-1, le=1)
    peka_ai_min_evidence_results: int = Field(default=1, ge=1, le=25)
    peka_ai_max_query_characters: int = Field(default=2000, ge=1, le=10000)
    peka_ai_max_top_k: int = Field(default=25, ge=1, le=50)
    peka_ai_default_top_k: int = Field(default=8, ge=1, le=25)
    peka_ai_max_evidence_characters_per_chunk: int = Field(
        default=6000, ge=256, le=50000
    )
    peka_ai_max_prior_messages: int = Field(default=8, ge=0, le=50)
    peka_ai_max_history_tokens: int = Field(default=1200, ge=0, le=16000)
    peka_ai_max_evidence_tokens: int = Field(default=2200, ge=128, le=64000)
    peka_ai_max_total_prompt_tokens: int = Field(default=4096, ge=1024, le=131072)
    peka_ai_secret_detection_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
