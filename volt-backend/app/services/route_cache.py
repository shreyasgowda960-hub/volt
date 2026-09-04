"""Route cache, and the split-freshness rule that is the whole point of it.

Distance and duration come back from one Google call and are stored in one
row, but they are read with two different rules:

  distance  — served for the full retention window. Road geometry does not
              change in a month.
  duration  — served for 15 minutes. Traffic does.

That split is why option (b) from the spec was rejected: a cache hit that
served a 20 km/h fallback duration would silently show the customer the exact
fake number this spec exists to delete. And it is why option (a) was
rejected too — calling Google for duration on every hit saves zero requests,
since one request returns both, so the cache would cost a table and buy
nothing.

The practical effect: the dominant hit is estimate -> create for the same
route seconds apart, which a 15 minute duration TTL captures completely. A
different customer booking the same popular route an hour later gets the
distance from cache and a fresh duration, which is exactly right.
"""

import logging
import time
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route_distance import RouteDistance
from app.services.routing import (
    DistanceSource,
    GoogleRoutingService,
    RouteResult,
    RoutingService,
)

logger = logging.getLogger(__name__)

# The terms allow 30 consecutive calendar days. 29 is headroom so a sweep that
# runs slightly late is not the thing that breaches the licence.
RETENTION_DAYS = 29

# Bengaluru traffic moves on a 30-60 minute scale, so 15 minutes sits inside
# the noise floor while still covering the estimate -> create window.
DURATION_TTL_SECONDS = 15 * 60

# Retention of 30 days needs nowhere near per-request precision, and the sweep
# is a DELETE on a hot path. Same throttle shape as the booking expiry sweep
# and the place cache, with the same per-process caveat: several instances each
# sweep independently, which is harmless because the DELETE is idempotent.
PURGE_MIN_INTERVAL_SECONDS = 3600

_last_purge_at: float | None = None

# Coordinates rounded to 4 decimals, about 11 metres. Same reasoning as the
# place cache: an exact match on raw GPS would never hit.
_KEY_PRECISION = 4


def reset_purge_throttle() -> None:
    """Clears the sweep throttle. Test hook only — module-level throttles need
    one, or the first test to sweep suppresses sweeping in every test that runs
    within the next interval, order-dependently."""
    global _last_purge_at
    _last_purge_at = None


def coordinate_key(lat: float, lng: float) -> str:
    return f"{round(lat, _KEY_PRECISION)},{round(lng, _KEY_PRECISION)}"


async def purge_expired(db: AsyncSession) -> int:
    """Deletes rows past the retention window. A real DELETE.

    Filtering stale rows out of reads is not deletion — the data would still
    be sitting in the table, which is the thing the licence forbids.

    KNOWN LIMITATION, same as the other two lazy sweeps: a completely idle
    service holds rows slightly past the window until someone asks for a fare.
    Acceptable with a day of headroom; a scheduled job is the real answer and
    arrives with the one that replaces lazy booking expiry.
    """
    global _last_purge_at

    now = time.monotonic()
    if _last_purge_at is not None and now - _last_purge_at < PURGE_MIN_INTERVAL_SECONDS:
        return 0
    # Claimed before the await, so a burst of concurrent requests produces one
    # sweep rather than one each.
    _last_purge_at = now

    result = await db.execute(
        delete(RouteDistance).where(
            RouteDistance.created_at < func.now() - timedelta(days=RETENTION_DAYS)
        )
    )
    await db.commit()
    if result.rowcount:
        logger.info("purged %s expired cached routes", result.rowcount)
    return result.rowcount


async def _store(
    db: AsyncSession, origin_key: str, dest_key: str, result: RouteResult
) -> None:
    """Upserts, restarting the retention clock.

    ON CONFLICT rather than select-then-insert: two customers estimating the
    same route simultaneously would otherwise race on the primary key. Same
    reasoning as claim_booking — let the database settle it in one statement.

    Refreshing created_at is correct rather than a way of dodging the limit:
    these values were genuinely just fetched from Google, so a new window
    legitimately starts now.
    """
    statement = pg_insert(RouteDistance).values(
        origin_key=origin_key,
        dest_key=dest_key,
        distance_m=result.distance_m,
        duration_s=result.duration_s,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[RouteDistance.origin_key, RouteDistance.dest_key],
            set_={
                "distance_m": statement.excluded.distance_m,
                "duration_s": statement.excluded.duration_s,
                "created_at": func.now(),
            },
        )
    )
    await db.commit()


async def route_cached(
    db: AsyncSession,
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    service: RoutingService | None = None,
) -> RouteResult:
    """Road distance and duration, from cache where the terms and traffic allow.

    `service` is injectable so tests can assert that a cache hit issues no
    outbound call at all — the one property that makes the cache worth having.
    """
    routing = service if service is not None else GoogleRoutingService()

    await purge_expired(db)

    origin_key = coordinate_key(origin_lat, origin_lng)
    dest_key = coordinate_key(dest_lat, dest_lng)

    row = (
        await db.execute(
            select(
                RouteDistance.distance_m,
                RouteDistance.duration_s,
                RouteDistance.created_at,
            ).where(
                RouteDistance.origin_key == origin_key,
                RouteDistance.dest_key == dest_key,
                # Never serve a row past retention even if the sweep is late.
                RouteDistance.created_at
                >= func.now() - timedelta(days=RETENTION_DAYS),
                # Duration is the binding constraint on a full hit. A row
                # whose distance is still good but whose duration has gone
                # stale is deliberately treated as a miss: we have to call
                # Google for a fresh duration anyway, and that same call
                # returns the distance, so there is nothing to reuse.
                RouteDistance.created_at
                >= func.now() - timedelta(seconds=DURATION_TTL_SECONDS),
            )
        )
    ).first()

    if row is not None:
        # A cached Google answer is still a Google answer — the source
        # describes how the number was derived, not how recently.
        return RouteResult(
            distance_m=row.distance_m,
            duration_s=row.duration_s,
            source=DistanceSource.google,
        )

    result = await routing.route(origin_lat, origin_lng, dest_lat, dest_lng)

    # Only Google results are cached. Caching a haversine fallback would make
    # a transient Google outage stick for 15 minutes after it recovered, and
    # would put a made-up distance behind a source that says "google".
    if result.source is DistanceSource.google:
        await _store(db, origin_key, dest_key, result)

    return result
