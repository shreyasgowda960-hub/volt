import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.auth import init_firebase
from app.config import get_settings
from app.database import engine
from app.errors import CodedHTTPException, coded_http_exception_handler
from app.routers import admin, bookings, drivers, places, service_area, vehicle_types
from app.services.storage import verify_storage_configured

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

    # Same treatment as credentials above, and for the same reason: config a
    # core flow cannot work without belongs at startup, not at first use. The
    # bucket name was missing in production for a whole deploy because nothing
    # checked it until a driver pressed Upload.
    #
    # The reachability half of this never raises — see verify_storage_configured.
    # Only a MISSING bucket name stops the process.
    await run_in_threadpool(verify_storage_configured)

    yield


app = FastAPI(
    title="VOLT API",
    version="0.1.0",
    docs_url="/docs",
    lifespan=lifespan,
)

# Renders a top-level `code` alongside `detail` for the errors that carry one.
# Registered for the subclass only, so every other error keeps FastAPI's own
# handler and the standard shape. See app/errors.py.
app.add_exception_handler(CodedHTTPException, coded_http_exception_handler)

app.include_router(bookings.router)
app.include_router(drivers.router)
app.include_router(vehicle_types.router)
app.include_router(service_area.router)
app.include_router(places.router)
app.include_router(admin.router)


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    """Liveness check that also proves the database is reachable."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok", "environment": settings.environment}
