"""Real road distance and duration, with a fallback that always answers.

Uses the **Routes API** (`computeRoutes`), not Distance Matrix. Google's own
docs put Distance Matrix in "Legacy status" — "This API is now in legacy mode.
Use Compute Route Matrix instead" — and the JS DistanceMatrixService is
deprecated as of 2026-02-25. computeRoutes rather than computeRouteMatrix
because this is one origin and one destination; the matrix method exists for
N x M and would mean parsing matrix elements to get a single pair. When driver
matching needs "which of these online drivers is nearest", that IS an N x M
problem and computeRouteMatrix is the right call then.

Request and response shapes taken from the current docs, not from memory:
  https://developers.google.com/maps/documentation/routes/compute_route_directions

Fare estimation sits on the critical path, so nothing here raises. Every
failure — timeout, non-200, quota rejection, malformed body, missing route —
falls back to the haversine estimate and says so in the result, because
"fares are approximate for an hour" beats "nobody can book".
"""

import logging
from typing import NamedTuple, Protocol

import httpx

from app.config import get_settings
from app.models.booking import DistanceSource
from app.utils.distance import eta_minutes, road_distance_m

logger = logging.getLogger(__name__)

_COMPUTE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# Only the two values we use. Routes API bills per request rather than per
# field, but a narrow mask keeps the response small and makes it obvious what
# this client depends on.
_FIELD_MASK = "routes.distanceMeters,routes.duration"

# TRAFFIC_AWARE moves the request from the Essentials SKU to Pro, so this is a
# deliberate spend. Justified because the duration is shown to a customer
# deciding whether to book, and in Bengaluru traffic is the dominant term in
# that number — TRAFFIC_UNAWARE free-flow duration would be wrong in a
# different direction from the flat 20km/h it replaces. Change this one
# constant to drop back to the cheaper tier.
_ROUTING_PREFERENCE = "TRAFFIC_AWARE"

# departureTime is deliberately omitted: it defaults to now, and an explicitly
# set "now" risks being in the past by the time the request reaches Google,
# which is an error.

# Short. A hanging Google request must not hang our endpoint, and the fallback
# is cheap — better an approximate fare in 4s than a correct one in 30.
_TIMEOUT = httpx.Timeout(4.0, connect=2.0)


class RouteResult(NamedTuple):
    distance_m: int
    duration_s: int
    source: DistanceSource


class RoutingService(Protocol):
    async def route(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
    ) -> RouteResult: ...


def haversine_fallback(
    origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float
) -> RouteResult:
    """The old behaviour, now the fallback.

    road_distance_m and eta_minutes are unchanged and stay correct for the
    service-area radius check, which wants straight-line distance from a
    centre point and must not move when this file changes.
    """
    distance_m = road_distance_m(origin_lat, origin_lng, dest_lat, dest_lng)
    return RouteResult(
        distance_m=distance_m,
        duration_s=eta_minutes(distance_m) * 60,
        source=DistanceSource.haversine,
    )


def _parse_duration_seconds(raw: object) -> int | None:
    """Routes API returns duration as a STRING with a trailing 's': "165s".

    Not a number, which is the kind of thing a client written from memory gets
    wrong and then silently reports every trip as taking zero seconds.
    """
    if not isinstance(raw, str) or not raw.endswith("s"):
        return None
    try:
        # Fractional seconds are permitted by the protobuf Duration encoding.
        return round(float(raw[:-1]))
    except ValueError:
        return None


class GoogleRoutingService:
    """Routes API client. Never raises; see the module docstring."""

    async def route(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
    ) -> RouteResult:
        settings = get_settings()
        api_key = settings.google_maps_api_key
        if not api_key:
            # Not an error worth alarming about on its own — a local checkout
            # without the key is a normal state — but it does mean every fare
            # is approximate, so it is a warning like the rest.
            logger.warning(
                "routing: GOOGLE_MAPS_API_KEY not set, using haversine fallback"
            )
            return haversine_fallback(origin_lat, origin_lng, dest_lat, dest_lng)

        body = {
            "origin": {
                "location": {
                    "latLng": {"latitude": origin_lat, "longitude": origin_lng}
                }
            },
            "destination": {
                "location": {"latLng": {"latitude": dest_lat, "longitude": dest_lng}}
            },
            "travelMode": "DRIVE",
            "routingPreference": _ROUTING_PREFERENCE,
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(
                    _COMPUTE_ROUTES_URL,
                    json=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Goog-Api-Key": api_key,
                        "X-Goog-FieldMask": _FIELD_MASK,
                    },
                )
        except httpx.HTTPError as e:
            # Covers timeouts, DNS failures, connection resets.
            return self._degraded(
                f"transport failure: {type(e).__name__}: {e}",
                origin_lat,
                origin_lng,
                dest_lat,
                dest_lng,
            )

        if response.status_code != 200:
            # 403 for a key or quota problem, 429 for rate limits, 400 for a
            # malformed request. All are ours to fix and none should stop a
            # customer booking, so they all degrade identically.
            return self._degraded(
                f"HTTP {response.status_code}: {response.text[:300]}",
                origin_lat,
                origin_lng,
                dest_lat,
                dest_lng,
            )

        try:
            payload = response.json()
        except ValueError as e:
            return self._degraded(
                f"unparseable body: {e}", origin_lat, origin_lng, dest_lat, dest_lng
            )

        routes = payload.get("routes")
        if not isinstance(routes, list) or not routes:
            # A genuinely unroutable pair (an island, a pedestrian-only zone)
            # answers 200 with no routes. Indistinguishable here from a
            # response shape change, and the handling is the same either way.
            return self._degraded(
                "no routes in response", origin_lat, origin_lng, dest_lat, dest_lng
            )

        first = routes[0]
        distance_m = first.get("distanceMeters")
        duration_s = _parse_duration_seconds(first.get("duration"))

        if not isinstance(distance_m, int) or duration_s is None:
            return self._degraded(
                f"malformed route: distanceMeters={distance_m!r} "
                f"duration={first.get('duration')!r}",
                origin_lat,
                origin_lng,
                dest_lat,
                dest_lng,
            )

        return RouteResult(
            distance_m=distance_m,
            duration_s=duration_s,
            source=DistanceSource.google,
        )

    def _degraded(
        self,
        reason: str,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
    ) -> RouteResult:
        # warning, not info: this is a degraded state and the whole point of
        # logging it is that it shows up when someone goes looking for why
        # fares dipped for an hour.
        logger.warning("routing: falling back to haversine — %s", reason)
        return haversine_fallback(origin_lat, origin_lng, dest_lat, dest_lng)


def default_routing_service() -> RoutingService:
    """The service every caller uses unless one is injected.

    A single factory rather than each caller constructing its own, for one
    concrete reason: it gives the test suite exactly one seam to close.
    Every fare estimate and every booking now makes a live, billable Routes
    request — there is no cache to absorb the second one — so the autouse
    guard in tests/conftest.py patches this function. Add a caller that
    constructs GoogleRoutingService() directly and it will bill real requests
    from the test suite.
    """
    return GoogleRoutingService()
