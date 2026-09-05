from unittest.mock import patch

import pytest
import pytest_asyncio

from app.database import engine
from app.services.booking import reset_expiry_throttle
from app.services.place_cache import reset_purge_throttle
from app.services.rate_limit import reset_rate_limits
from app.services.routing import RouteResult, haversine_fallback
from app.models.booking import DistanceSource


@pytest.fixture(autouse=True)
def _reset_throttles():
    """Both sweeps are throttled by module-level state, so without this the
    first test to sweep would suppress the sweep in every test that ran
    within the next interval — and which tests those are depends on
    ordering. Reset before each test so every one sees a fresh throttle.

    The rate limiter is the same hazard pointing the other way: its counters
    are module-level too, so a test that exhausts a budget would 429 every
    later test sharing that key, again depending on ordering."""
    reset_expiry_throttle()
    reset_purge_throttle()
    reset_rate_limits()


class _FakeRoutingService:
    """Stands in for the Routes API in every test that is not about routing.

    Returns the haversine numbers but labelled `google`. Two reasons for that
    exact choice:

      - Distances and therefore fares stay identical to what they were before
        spec 014, so no existing test's expectations move for a reason that
        has nothing to do with what it is testing.
      - The source is `google`, so the booking-creation path exercises the
        real provenance wiring rather than the fallback branch.

    Tests that care about the client itself mock httpx and construct
    GoogleRoutingService directly, which this does not touch.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[float, float, float, float]] = []

    async def route(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
    ) -> RouteResult:
        self.calls.append((origin_lat, origin_lng, dest_lat, dest_lng))
        fallback = haversine_fallback(origin_lat, origin_lng, dest_lat, dest_lng)
        return RouteResult(
            distance_m=fallback.distance_m,
            duration_s=fallback.duration_s,
            source=DistanceSource.google,
        )


@pytest.fixture(autouse=True)
def _block_outbound_routing():
    """Nothing in the suite may call the Routes API for real.

    A spend guard, not just determinism, and MORE load-bearing since the
    route cache was removed for licence reasons: there is no longer any cache
    to absorb a repeat, so every estimate and every booking is its own live
    billable request. The booking tests alone would bill dozens.

    Patched at default_routing_service, which is the single seam every caller
    goes through. GoogleRoutingService itself stays real, so the tests in
    test_routing.py that mock its HTTP layer are unaffected.
    """
    with patch(
        "app.services.routing.default_routing_service",
        lambda: _FakeRoutingService(),
    ):
        yield


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_after_test():
    """Each pytest-asyncio test gets its own event loop, but `engine` is a
    module-level singleton whose connection pool is tied to whichever loop
    created it. Without disposing it, the next test's loop tries to reuse a
    connection from a now-closed loop and blows up."""
    yield
    await engine.dispose()
