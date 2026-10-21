from functools import lru_cache
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    environment: str = "development"
    firebase_credentials_path: str = "secrets/firebase-service-account.json"

    # --- Service area ----------------------------------------------------
    # Env-driven rather than constants, deliberately. The radius can be
    # narrowed to a couple of kilometres from the Render dashboard for a
    # real-world field test — no deploy, no app rebuild, because both apps
    # read it from GET /api/v1/service-area rather than hardcoding it.
    #
    # 12.9716, 77.5946 is the conventional Bengaluru city-centre coordinate.
    # Whether it is the right *operational* centre is a business question:
    # if most demand sits in the east, centring there buys more useful
    # coverage than centring on Vidhana Soudha does.
    service_center_lat: float = 12.9716
    service_center_lng: float = 77.5946
    service_radius_km: float = 25.0

    # --- Google Maps Platform --------------------------------------------
    # Server-side key, never shipped to a client. The apps call our own
    # proxy endpoints and those call Google, because an Android application
    # restriction does not apply to the Places or Geocoding *web services* —
    # a client-side key would therefore have to be unrestricted, sitting
    # extractable inside every APK.
    #
    # Restrictions on this key: application restriction NONE (Render's free
    # plan has no static outbound IP, only CIDR ranges shared with every
    # other tenant in the region), API restrictions to exactly Places API
    # (New) and Geocoding API, plus a per-API daily quota cap — the quota is
    # what actually bounds the damage if it ever leaks.
    #
    # Optional so the app still boots without it: only the Places proxy
    # endpoints need it, and they fail with a clear 503 rather than taking
    # the whole service down at import time.
    google_maps_api_key: str | None = None

    # --- Admin review (spec 017) -----------------------------------------
    # INTERIM, AND WEAK BY DESIGN. A single shared secret protecting the
    # document review endpoints. It has NO AUDIT TRAIL — every action is
    # "whoever had the token" — and it cannot be revoked for one person
    # without revoking it for everyone, which at one reviewer means it cannot
    # be revoked at all without a redeploy.
    #
    # Accepted because the alternative today is an admin user table and a
    # login flow for a single person. It is replaced by real admin auth when
    # the React dashboard arrives, or the moment a second person reviews
    # documents — see docs/future-plans.md.
    #
    # Optional so the app still boots without it: the review endpoints answer
    # 503 when it is unset rather than accepting every request, which is the
    # failure direction that matters.
    admin_review_token: str | None = None

    # --- Firebase Storage (spec 017) -------------------------------------
    # The bucket driver documents live in, e.g. volt-2b36f.firebasestorage.app.
    #
    # REQUIRED, AND REQUIRED HERE — this type is the single source of truth.
    # It was `str | None = None` with the requirement living only in a comment
    # and a startup check, which is three places to disagree and exactly how
    # the next person misreads it. min_length=1 because an env var set to ""
    # is what a half-filled dashboard produces and must not read as configured.
    #
    # It was neither required nor read until 8 Oct 2026:
    # firebase_admin.initialize_app() was called with no options, so
    # firebase_admin.storage.bucket() raised "Storage bucket name not
    # specified" — but only when a driver actually uploaded, in production,
    # after a deploy that looked completely healthy.
    #
    # Being required HERE means configuration fails when it is first loaded,
    # which is earlier than any startup check can run and earlier than the app
    # finishes importing. app/services/storage.py keeps only the reachability
    # probe, which deliberately never raises.
    #
    # NOT derived from the credentials' project_id even though the
    # conventional name is {project_id}.firebasestorage.app. A derived bucket
    # name is a guess, and a guess that is wrong points the one piece of
    # genuinely sensitive data VOLT holds at a bucket nobody is watching.
    firebase_storage_bucket: str = Field(min_length=1)

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


class MissingConfiguration(RuntimeError):
    """.env is incomplete or invalid.

    Exists so an incomplete .env produces a sentence naming the variables
    rather than a pydantic traceback. The person who hits this is usually
    someone who has just cloned the repo, and the fix is always the same
    file — so the error says which one.
    """


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is parsed once per process, not per request."""
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as e:
        names = sorted(
            {
                str(err["loc"][0]).upper()
                for err in e.errors()
                if err.get("loc")
            }
        )
        raise MissingConfiguration(
            "Configuration is incomplete or invalid: "
            + ", ".join(names)
            # ASCII only: this is read in a Render log or a Windows console,
            # and a non-ASCII dash renders there as mojibake.
            + ". Copy volt-backend/.env.example to .env and fill these in. "
            "docs/collaboration.md has the onboarding checklist."
        ) from e
