"""Coordinate cache for Google place ids, and its retention sweep.

Two rules from the Maps Platform terms shape everything here:

  - a place id may be stored indefinitely;
  - latitude/longitude may be cached for at most 30 consecutive days, after
    which they must be DELETED.

"Deleted" is doing real work in that sentence. Filtering stale rows out of
reads is not deletion — the data is still sitting in the table, and the terms
say to remove it. So `purge_expired` issues an actual DELETE, and reads
additionally refuse anything already past the window in case the sweep has
not run yet.
"""

import logging
import time
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.place_coordinate import PlaceCoordinate

logger = logging.getLogger(__name__)

# The terms say 30 consecutive calendar days. 29 is deliberate headroom: a
# sweep that runs slightly late must not be the thing that breaches it.
RETENTION_DAYS = 29

# 30-day retention needs nowhere near per-request precision, and the sweep is
# a DELETE on a hot path. Same throttle shape as the booking expiry sweep,
# and the same per-process caveat: several instances each sweep independently,
# which is harmless because the DELETE is idempotent.
PURGE_MIN_INTERVAL_SECONDS = 3600

_last_purge_at: float | None = None


def reset_purge_throttle() -> None:
    """Clears the sweep throttle. Test hook only — see the booking-expiry
    equivalent for why module-level throttles need one."""
    global _last_purge_at
    _last_purge_at = None


async def purge_expired(db: AsyncSession) -> int:
    """Deletes coordinates cached more than RETENTION_DAYS ago.

    A real DELETE, not a read-time filter. Uses the database clock so
    instances with drifting clocks cannot disagree about what has expired.

    KNOWN LIMITATION, same as the booking expiry sweep: this is lazy, so a
    completely idle service holds rows slightly past the window until someone
    calls an address endpoint. Acceptable while the retention limit is 30
    days and the headroom is a day; a scheduled job is the real answer and
    arrives with the same one that replaces lazy expiry.
    """
    global _last_purge_at

    now = time.monotonic()
    if _last_purge_at is not None and now - _last_purge_at < PURGE_MIN_INTERVAL_SECONDS:
        return 0
    # Claimed before the await, so a burst of concurrent requests produces one
    # sweep rather than one each.
    _last_purge_at = now

    result = await db.execute(
        delete(PlaceCoordinate).where(
            PlaceCoordinate.cached_at
            < func.now() - timedelta(days=RETENTION_DAYS)
        )
    )
    await db.commit()
    if result.rowcount:
        logger.info("purged %s expired cached coordinates", result.rowcount)
    return result.rowcount


async def get_coordinates(
    db: AsyncSession, place_id: str
) -> tuple[float, float] | None:
    """Cached coordinates, or None.

    The cached_at floor is belt-and-braces on top of purge_expired: if the
    sweep is late, an over-age row must still never be served.
    """
    result = await db.execute(
        select(PlaceCoordinate.lat, PlaceCoordinate.lng).where(
            PlaceCoordinate.place_id == place_id,
            PlaceCoordinate.cached_at
            >= func.now() - timedelta(days=RETENTION_DAYS),
        )
    )
    row = result.first()
    return (row.lat, row.lng) if row is not None else None


async def store_coordinates(
    db: AsyncSession, place_id: str, lat: float, lng: float
) -> None:
    """Upserts coordinates and restarts the retention clock.

    ON CONFLICT rather than select-then-insert: two requests resolving the
    same place simultaneously would otherwise race on the primary key, and
    one would fail on a duplicate. The same reasoning as claim_booking — let
    the database settle it in one statement.

    Refreshing cached_at on conflict is correct, not a way of dodging the
    limit: these coordinates were genuinely just fetched from Google, so a
    new 30-day window legitimately starts now.
    """
    statement = pg_insert(PlaceCoordinate).values(
        place_id=place_id, lat=lat, lng=lng
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[PlaceCoordinate.place_id],
            set_={
                "lat": statement.excluded.lat,
                "lng": statement.excluded.lng,
                "cached_at": func.now(),
            },
        )
    )
    await db.commit()
