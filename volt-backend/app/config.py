from functools import lru_cache
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    environment: str = "development"
    firebase_credentials_path: str = "secrets/firebase-service-account.json"

    # Deployment: full service account JSON as a string. Takes precedence over
    # the file path when set, because there is no file system to write to.
    firebase_credentials_json: str | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        """Render emits `postgresql://...` (or the legacy `postgres://`), and
        sometimes appends `?sslmode=...`. SQLAlchemy's asyncpg dialect needs
        the `+asyncpg` driver segment, and asyncpg itself rejects `sslmode`
        as a connect kwarg, so both are fixed up here before anything else
        touches the URL."""
        if v.startswith("postgres://"):
            v = "postgresql+asyncpg://" + v[len("postgres://") :]
        elif v.startswith("postgresql://") and not v.startswith(
            "postgresql+asyncpg://"
        ):
            v = "postgresql+asyncpg://" + v[len("postgresql://") :]

        parts = urlsplit(v)
        if parts.query:
            query = [
                (k, val) for k, val in parse_qsl(parts.query) if k != "sslmode"
            ]
            parts = parts._replace(query="&".join(f"{k}={val}" for k, val in query))
            v = urlunsplit(parts)

        return v


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is parsed once per process, not per request."""
    return Settings()  # type: ignore[call-arg]
