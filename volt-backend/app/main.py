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
