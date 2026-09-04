"""Spec 014 — the route cache and its split freshness rule.

The property that makes this cache worth having is that a hit issues no
outbound call at all, so every test here counts calls on an injected fake
rather than trusting the returned values.
"""

from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, update

from app.database import SessionLocal
from app.models.booking import DistanceSource
from app.models.route_distance import RouteDistance
from app.services import route_cache
from app.services.routing import RouteResult

KORAMANGALA = (12.9352, 77.6245)
WHITEFIELD = (12.9698, 77.7500)

_GOOGLE = RouteResult(
    distance_m=23456, duration_s=1837, source=DistanceSource.google
)


class _CountingService:
    """Records every call so a test can prove a hit made none."""

    def __init__(self, result: RouteResult = _GOOGLE):
        self.result = result
        self.calls = 0

    async def route(self, *_args) -> RouteResult:
        self.calls += 1
        return self.result


async def _clear(*pairs: tuple[float, float]) -> None:
    keys = [route_cache.coordinate_key(lat, lng) for lat, lng in pairs]
    async with SessionLocal() as db:
        await db.execute(
            delete(RouteDistance).where(
                RouteDistance.origin_key.in_(keys) | RouteDistance.dest_key.in_(keys)
            )
        )
        await db.commit()


async def _backdate(origin, dest, **delta) -> None:
    """Ages a cached row using the database clock."""
    async with SessionLocal() as db:
        await db.execute(
            update(RouteDistance)
            .where(
                RouteDistance.origin_key == route_cache.coordinate_key(*origin),
                RouteDistance.dest_key == route_cache.coordinate_key(*dest),
            )
            .values(created_at=func.now() - timedelta(**delta))
        )
        await db.commit()


# --- Keys -----------------------------------------------------------------


def test_coordinates_round_to_about_eleven_metres():
    """Raw GPS gives 12.93521847, so two taps on one spot produce different
    values and an exact match would never hit."""
    assert route_cache.coordinate_key(12.93521847, 77.62449321) == "12.9352,77.6245"
    # Within ~11m collapses to the same key...
    assert route_cache.coordinate_key(12.935214, 77.624493) == route_cache.coordinate_key(
        12.935241, 77.624512
    )
    # ...and a genuinely different place does not.
    assert route_cache.coordinate_key(12.9352, 77.6245) != route_cache.coordinate_key(
        12.9698, 77.7500
    )


# --- Miss, then hit -------------------------------------------------------


@pytest.mark.asyncio
async def test_miss_calls_google_then_hit_calls_nothing():
    await _clear(KORAMANGALA, WHITEFIELD)
    service = _CountingService()

    async with SessionLocal() as db:
        first = await route_cache.route_cached(
            db, *KORAMANGALA, *WHITEFIELD, service=service
        )
        assert first == _GOOGLE
        assert service.calls == 1

        second = await route_cache.route_cached(
            db, *KORAMANGALA, *WHITEFIELD, service=service
        )

    # The whole point of the cache: no second outbound call.
    assert service.calls == 1
    assert second.distance_m == _GOOGLE.distance_m
    assert second.duration_s == _GOOGLE.duration_s
    # A cached Google answer is still a Google answer — source describes how
    # the number was derived, not how recently.
    assert second.source is DistanceSource.google

    await _clear(KORAMANGALA, WHITEFIELD)


@pytest.mark.asyncio
async def test_nearby_coordinates_hit_the_same_row():
    """The estimate and the booking come from the same tap but rarely the
    same float. Rounding is what makes the create-booking recompute a hit."""
    await _clear(KORAMANGALA, WHITEFIELD)
    service = _CountingService()

    async with SessionLocal() as db:
        await route_cache.route_cached(
            db, *KORAMANGALA, *WHITEFIELD, service=service
        )
        # Same place, ~2m away in float terms.
        await route_cache.route_cached(
            db,
            KORAMANGALA[0] + 0.000012,
            KORAMANGALA[1] - 0.000009,
            *WHITEFIELD,
            service=service,
        )

    assert service.calls == 1

    await _clear(KORAMANGALA, WHITEFIELD)


# --- The split freshness rule --------------------------------------------


@pytest.mark.asyncio
async def test_stale_duration_forces_a_refetch_even_though_distance_is_fine():
    """Distance is good for the full retention window and duration is not.

    A row whose duration has aged out is treated as a miss, because the only
    way to get a fresh duration is a call that returns the distance anyway —
    there is nothing left to reuse. This is why option (b) was rejected:
    serving the 20km/h fallback duration on a hit would show the customer the
    exact fake number spec 014 exists to delete.
    """
    await _clear(KORAMANGALA, WHITEFIELD)
    service = _CountingService()

    async with SessionLocal() as db:
        await route_cache.route_cached(
            db, *KORAMANGALA, *WHITEFIELD, service=service
        )
        assert service.calls == 1

    # Older than the duration TTL, far younger than retention.
    await _backdate(
        KORAMANGALA, WHITEFIELD,
        seconds=route_cache.DURATION_TTL_SECONDS + 60,
    )

    async with SessionLocal() as db:
        again = await route_cache.route_cached(
            db, *KORAMANGALA, *WHITEFIELD, service=service
        )

    assert service.calls == 2, "a stale duration must not be served"
    assert again.source is DistanceSource.google

    await _clear(KORAMANGALA, WHITEFIELD)


@pytest.mark.asyncio
async def test_row_past_retention_is_never_served():
    """Belt and braces on top of the purge: if the sweep is late, an
    over-age row must still not be handed out."""
    await _clear(KORAMANGALA, WHITEFIELD)
    service = _CountingService()

    async with SessionLocal() as db:
        await route_cache.route_cached(
            db, *KORAMANGALA, *WHITEFIELD, service=service
        )

    await _backdate(
        KORAMANGALA, WHITEFIELD, days=route_cache.RETENTION_DAYS + 1
    )

    async with SessionLocal() as db:
        # Throttle reset by conftest, so the purge in route_cached will run
        # and delete it; either way it must not be served from cache.
        await route_cache.route_cached(
            db, *KORAMANGALA, *WHITEFIELD, service=service
        )

    assert service.calls == 2

    await _clear(KORAMANGALA, WHITEFIELD)


# --- What must not be cached ---------------------------------------------


@pytest.mark.asyncio
async def test_a_haversine_fallback_is_never_cached():
    """Caching a degraded answer would make a transient Google outage stick
    for the full TTL after it recovered, and would put an invented distance
    behind a row whose source says google."""
    await _clear(KORAMANGALA, WHITEFIELD)
    degraded = _CountingService(
        RouteResult(distance_m=19787, duration_s=3540, source=DistanceSource.haversine)
    )

    async with SessionLocal() as db:
        result = await route_cache.route_cached(
            db, *KORAMANGALA, *WHITEFIELD, service=degraded
        )
        assert result.source is DistanceSource.haversine

        stored = (
            await db.execute(
                select(func.count())
                .select_from(RouteDistance)
                .where(
                    RouteDistance.origin_key
                    == route_cache.coordinate_key(*KORAMANGALA)
                )
            )
        ).scalar_one()

    assert stored == 0, "a fallback answer must not enter the cache"

    # And once Google recovers, the next call is a miss that stores properly.
    recovered = _CountingService()
    async with SessionLocal() as db:
        good = await route_cache.route_cached(
            db, *KORAMANGALA, *WHITEFIELD, service=recovered
        )
    assert good.source is DistanceSource.google
    assert recovered.calls == 1

    await _clear(KORAMANGALA, WHITEFIELD)


# --- Retention ------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_actually_deletes_rows_past_retention():
    """The terms say delete, so this asserts the row is GONE from the table.

    Filtering stale rows out of reads is not deletion — the data would still
    be sitting there, which is the thing the licence forbids. Same assertion
    shape as the place-coordinate purge.
    """
    await _clear(KORAMANGALA, WHITEFIELD)
    service = _CountingService()

    async with SessionLocal() as db:
        await route_cache.route_cached(
            db, *KORAMANGALA, *WHITEFIELD, service=service
        )

    await _backdate(
        KORAMANGALA, WHITEFIELD, days=route_cache.RETENTION_DAYS + 1
    )

    async with SessionLocal() as db:
        route_cache.reset_purge_throttle()
        deleted = await route_cache.purge_expired(db)
        assert deleted == 1

        remaining = (
            await db.execute(
                select(func.count())
                .select_from(RouteDistance)
                .where(
                    RouteDistance.origin_key
                    == route_cache.coordinate_key(*KORAMANGALA)
                )
            )
        ).scalar_one()

    assert remaining == 0

    await _clear(KORAMANGALA, WHITEFIELD)


@pytest.mark.asyncio
async def test_purge_is_throttled():
    """It runs on every fare request, so it is throttled the same way the
    booking expiry and place-coordinate sweeps are."""
    await _clear(KORAMANGALA, WHITEFIELD)
    service = _CountingService()

    async with SessionLocal() as db:
        await route_cache.route_cached(
            db, *KORAMANGALA, *WHITEFIELD, service=service
        )
    await _backdate(
        KORAMANGALA, WHITEFIELD, days=route_cache.RETENTION_DAYS + 1
    )

    async with SessionLocal() as db:
        route_cache.reset_purge_throttle()
        assert await route_cache.purge_expired(db) == 1

        # Second expired row inside the throttle window: skipped.
        await route_cache.route_cached(
            db, *KORAMANGALA, *WHITEFIELD, service=service
        )
    await _backdate(
        KORAMANGALA, WHITEFIELD, days=route_cache.RETENTION_DAYS + 1
    )

    async with SessionLocal() as db:
        assert await route_cache.purge_expired(db) == 0
        # Clearing the throttle is the only thing between it and deletion,
        # which proves the throttle spared it rather than the predicate.
        route_cache.reset_purge_throttle()
        assert await route_cache.purge_expired(db) == 1

    await _clear(KORAMANGALA, WHITEFIELD)
