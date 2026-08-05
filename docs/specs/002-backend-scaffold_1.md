# Spec 002 — Backend scaffold (FastAPI + PostgreSQL)

Build mode. Implement exactly as written. Do not improvise.

## Guardrails — read before starting

- **Do NOT create any SQLAlchemy models, tables, or Alembic migrations.** The
  `bookings` and `users` schema is being designed by hand in Learn mode. This
  spec stops at a working health endpoint.
- **Do NOT add dependencies** beyond the six in `requirements.txt` below.
- **Do NOT touch `customer_app/`.** This is backend only.
- **Do NOT commit `.env`.** Create it, but verify `git status` does not list it.
- If a prerequisite check below fails, **stop and report** rather than working
  around it or installing things yourself.

## Decisions already made — do not re-litigate

| Decision | Value | Why |
|---|---|---|
| Money storage | Integer paise (`fare_paise`) | Razorpay's API takes paise; no conversion boundary |
| Cancellation | Free any time before pickup | No fee column needed; rule lives in a service |
| Goods on booking | Description + approximate weight | Drives vehicle choice, matters for disputes |
| Booking IDs | Internal integer PK + separate public code | Sequential public IDs leak order volume and are enumerable |
| DB driver | `asyncpg`, async SQLAlchemy | Conventions require `async def` for I/O-bound routes |
| Postgres | Local install, not Docker | Docker comes at deployment; one new tool at a time |

## Prerequisites — verify first, report and stop if either fails

```powershell
python --version          # must be 3.11+
```

```powershell
& 'C:\Program Files\PostgreSQL\17\bin\psql.exe' -U postgres -c "SELECT version();"
```

Adjust the `17` to whichever version directory exists under
`C:\Program Files\PostgreSQL\`. This prompts for the postgres password.

If Postgres is not installed, stop. The user must install it from
https://www.postgresql.org/download/windows/ first.

Then create the database (skip without error if it already exists):

```powershell
& 'C:\Program Files\PostgreSQL\17\bin\psql.exe' -U postgres -c "CREATE DATABASE volt_dev;"
```

## Step 1 — Virtual environment

```powershell
cd $env:USERPROFILE\projects\volt
mkdir volt-backend
cd volt-backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Prompt must show `(.venv)`. If PowerShell blocks the activation script:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## Step 2 — New file: `volt-backend/requirements.txt`

```
fastapi
uvicorn[standard]
sqlalchemy[asyncio]
asyncpg
alembic
pydantic-settings
```

What each is for (do not add anything else):

- **fastapi** — web framework
- **uvicorn** — ASGI server; FastAPI cannot listen on a port by itself
- **sqlalchemy[asyncio]** — ORM, async variant
- **asyncpg** — async Postgres driver, replaces sync-only psycopg2
- **alembic** — schema migrations; installed now, not configured in this spec
- **pydantic-settings** — typed `.env` loading; split out of Pydantic core in v2

Install:

```powershell
pip install -r requirements.txt
```

## Step 3 — New file: `volt-backend/.env.example`

```
# Copy to .env and fill in real values. Never commit .env.
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5432/volt_dev
ENVIRONMENT=development
```

## Step 4 — New file: `volt-backend/.env`

Same two keys. Ask the user for the actual postgres password rather than
guessing or inventing a placeholder that will fail at startup.

The `postgresql+asyncpg://` prefix matters — a plain `postgresql://` URL fails
at startup with an unhelpful error.

After creating it, run `git status` from the repo root and confirm `.env` is
**not** listed. If it is, the root `.gitignore` needs fixing before any commit.

## Step 5 — New file: `volt-backend/app/__init__.py`

Empty file. Makes `app` an importable package.

## Step 6 — New file: `volt-backend/app/config.py`

```python
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
```

## Step 7 — New file: `volt-backend/app/database.py`

```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.environment == "development",
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Every model inherits from this. Alembic discovers tables through it."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency. One session per request, always closed."""
    async with SessionLocal() as session:
        yield session
```

Three settings worth understanding rather than copying blindly:

- `echo=True` in development prints every SQL statement SQLAlchemy generates.
- `pool_pre_ping` tests a pooled connection before handing it out, avoiding
  stale-connection errors after the laptop sleeps.
- `expire_on_commit=False` allows reading an object's attributes after
  `commit()`. Without it, every attribute access post-commit fires a new query.

## Step 8 — New file: `volt-backend/app/main.py`

```python
from fastapi import FastAPI
from sqlalchemy import text

from app.config import get_settings
from app.database import engine

settings = get_settings()

app = FastAPI(
    title="VOLT API",
    version="0.1.0",
    docs_url="/docs",
)


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    """Liveness check that also proves the database is reachable."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok", "environment": settings.environment}
```

## Step 9 — Create the empty directories the conventions require

Create these with a `.gitkeep` file in each so git tracks them empty:

```
volt-backend/app/routers/
volt-backend/app/models/
volt-backend/app/schemas/
volt-backend/app/services/
volt-backend/app/utils/
volt-backend/tests/
```

Do not put any code in them yet.

## Step 10 — Verify

```powershell
uvicorn app.main:app --reload
```

Run from inside `volt-backend/` with the venv active.

Then confirm both:

- `http://127.0.0.1:8000/api/v1/health` returns
  `{"status":"ok","environment":"development"}`
- `http://127.0.0.1:8000/docs` renders the auto-generated API docs

If startup fails, the cause is almost always `DATABASE_URL` — wrong password,
wrong port, missing `+asyncpg`, or the `volt_dev` database not created. Report
the exact traceback rather than guessing at fixes.

## Step 11 — Update `CLAUDE.md`

Add to the "Current state" section at the repo root:

```
Backend: volt-backend/ scaffolded. FastAPI + async SQLAlchemy + asyncpg.
Health endpoint at /api/v1/health confirms DB connectivity. No models, no
migrations, no real endpoints yet — bookings schema being designed by hand.
Postgres: local install, database volt_dev.
Money convention: integer paise, columns suffixed _paise.
```

## Step 12 — Stop

Report:

1. Every file created, with paths
2. Output of the health endpoint
3. Confirmation that `git status` does not list `.env`
4. Anything in this spec you deviated from, and why

Then stop. Do not design the bookings schema, do not run `alembic init`, do not
create models. Wait for the next instruction.
