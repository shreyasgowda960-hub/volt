import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.auth import init_firebase
from app.config import get_settings
from app.database import engine
from app.routers import bookings, drivers, service_area, vehicle_types

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_firebase()
    except Exception:
        logger.error(
            "Firebase initialization failed. Check that FIREBASE_CREDENTIALS_JSON "
            "(deployed) or FIREBASE_CREDENTIALS_PATH (local) points to valid "
            "service account credentials."
        )
        raise
    yield


app = FastAPI(
    title="VOLT API",
    version="0.1.0",
    docs_url="/docs",
    lifespan=lifespan,
)

app.include_router(bookings.router)
app.include_router(drivers.router)
app.include_router(vehicle_types.router)
app.include_router(service_area.router)


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    """Liveness check that also proves the database is reachable."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok", "environment": settings.environment}
