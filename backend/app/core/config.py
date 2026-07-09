# app/core/config.py

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
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

    database_url: str = Field(
        default="postgresql+psycopg://peka:peka@localhost:5432/peka_platform"
    )

    log_level: str = Field(default="INFO")

    platform_admin_jwt_secret: str = Field(default="change-me-local-only")
    platform_admin_jwt_algorithm: str = Field(default="HS256")
    platform_admin_access_token_minutes: int = Field(default=60)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
