from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is parsed once per process, not per request."""
    return Settings()  # type: ignore[call-arg]
