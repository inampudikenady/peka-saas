from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PEKA SaaS API"
    app_version: str = "0.1.0"
    environment: str = "dev"

    database_url: str = "postgresql+psycopg://peka:peka@localhost:5432/peka_saas"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
