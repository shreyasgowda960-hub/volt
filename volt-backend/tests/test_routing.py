"""Spec 014 — the Routes API client and its fallback.

Google is never called here. The client's HTTP layer is mocked, which tests
our parsing and our degradation; step B8's single live call is what tests the
integration. A mocked test proves your code, not your request shape.

The fallback cases are the point of this file. Fare estimation sits on the
critical path, so every way Google can fail has to end in a usable answer
labelled `haversine` — and each of these tests fails if the source label is
wrong, which was verified by mutation rather than assumed.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.config import get_settings
from app.models.booking import DistanceSource
from app.services.routing import (
    GoogleRoutingService,
    _parse_duration_seconds,
    haversine_fallback,
)

KORAMANGALA = (12.9352, 77.6245)
WHITEFIELD = (12.9698, 77.7500)


def _with_key():
    """The client short-circuits to the fallback without a key, so the HTTP
    paths need one present. Value is irrelevant — nothing reaches Google."""
    get_settings.cache_clear()
    return patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "test-key-not-real"})


def _response(status: int = 200, json_body: object = None, text: str = ""):
    request = httpx.Request("POST", "https://routes.googleapis.com/x")
    if json_body is not None:
        return httpx.Response(status, json=json_body, request=request)
    return httpx.Response(status, text=text, request=request)


async def _route(**post_kwargs):
    service = GoogleRoutingService()
    with _with_key():
        try:
            with patch.object(
                httpx.AsyncClient, "post", new=AsyncMock(**post_kwargs)
            ):
                return await service.route(*KORAMANGALA, *WHITEFIELD)
        finally:
            get_settings.cache_clear()


# --- Duration parsing -----------------------------------------------------


def test_duration_parses_the_seconds_suffix():
    """Routes API returns duration as a STRING with a trailing 's', not a
    number. A client written from memory treats it as an int, gets None, and
    reports every trip as taking no time at all."""
    assert _parse_duration_seconds("165s") == 165
    # protobuf Duration permits fractional seconds.
    assert _parse_duration_seconds("165.4s") == 165
    assert _parse_duration_seconds("165.6s") == 166


def test_duration_rejects_anything_that_is_not_that_shape():
    for bad in (165, None, "165", "s", "", "abcs", {"seconds": 165}):
        assert _parse_duration_seconds(bad) is None, bad


# --- Success --------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_returns_googles_numbers():
    result = await _route(
        return_value=_response(
            200, {"routes": [{"distanceMeters": 23456, "duration": "1837s"}]}
        )
    )
    assert result.distance_m == 23456
    assert result.duration_s == 1837
    assert result.source is DistanceSource.google


@pytest.mark.asyncio
async def test_success_sends_the_verified_request_shape():
    """Asserts on the request we actually send, because the field mask and the
    nested latLng shape are exactly what a from-memory client gets wrong —
    and a wrong field mask returns 200 with the fields missing."""
    post = AsyncMock(
        return_value=_response(
            200, {"routes": [{"distanceMeters": 100, "duration": "10s"}]}
        )
    )
    service = GoogleRoutingService()
    with _with_key():
        try:
            with patch.object(httpx.AsyncClient, "post", new=post):
                await service.route(*KORAMANGALA, *WHITEFIELD)
        finally:
            get_settings.cache_clear()

    kwargs = post.await_args.kwargs
    body, headers = kwargs["json"], kwargs["headers"]

    assert body["origin"]["location"]["latLng"] == {
        "latitude": KORAMANGALA[0],
        "longitude": KORAMANGALA[1],
    }
    assert body["destination"]["location"]["latLng"] == {
        "latitude": WHITEFIELD[0],
        "longitude": WHITEFIELD[1],
    }
    assert body["travelMode"] == "DRIVE"
    assert body["routingPreference"] == "TRAFFIC_AWARE"
    # departureTime deliberately absent: it defaults to now, and an
    # explicitly set "now" can be in the past by the time Google sees it.
    assert "departureTime" not in body
    assert headers["X-Goog-FieldMask"] == "routes.distanceMeters,routes.duration"
    assert headers["X-Goog-Api-Key"] == "test-key-not-real"


# --- Every failure path degrades ------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "label,post_kwargs",
    [
        ("timeout", {"side_effect": httpx.TimeoutException("timed out")}),
        ("connect error", {"side_effect": httpx.ConnectError("no route to host")}),
        (
            "quota rejected",
            {"return_value": _response(403, text="RESOURCE_EXHAUSTED: quota")},
        ),
        ("rate limited", {"return_value": _response(429, text="too many requests")}),
        ("bad request", {"return_value": _response(400, text="INVALID_ARGUMENT")}),
        ("unparseable body", {"return_value": _response(200, text="<html>nope")}),
        ("no routes key", {"return_value": _response(200, {})}),
        ("empty routes", {"return_value": _response(200, {"routes": []})}),
        (
            "missing distance",
            {"return_value": _response(200, {"routes": [{"duration": "60s"}]})},
        ),
        (
            "distance not an int",
            {
                "return_value": _response(
                    200, {"routes": [{"distanceMeters": "23456", "duration": "60s"}]}
                )
            },
        ),
        (
            "duration not a duration",
            {
                "return_value": _response(
                    200, {"routes": [{"distanceMeters": 23456, "duration": 60}]}
                )
            },
        ),
    ],
)
async def test_every_failure_falls_back_to_haversine(label, post_kwargs):
    """A fare service that fails closed on a third-party outage is worse than
    one that degrades. Every one of these must still produce a bookable
    number, and must say it is not Google's."""
    result = await _route(**post_kwargs)
    expected = haversine_fallback(*KORAMANGALA, *WHITEFIELD)

    assert result.source is DistanceSource.haversine, label
    assert result.distance_m == expected.distance_m, label
    assert result.duration_s == expected.duration_s, label


@pytest.mark.asyncio
async def test_missing_api_key_falls_back_without_calling_anything():
    """A checkout without the key is a normal state and must still price
    bookings — but it must not silently look like a Google answer."""
    post = AsyncMock()
    get_settings.cache_clear()
    try:
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": ""}):
            with patch.object(httpx.AsyncClient, "post", new=post):
                result = await GoogleRoutingService().route(
                    *KORAMANGALA, *WHITEFIELD
                )
    finally:
        get_settings.cache_clear()

    assert result.source is DistanceSource.haversine
    post.assert_not_awaited()


def test_fallback_matches_the_old_behaviour_exactly():
    """The fallback must be the pre-014 numbers, not a new approximation.

    19787m is the figure test_distance.py asserted when haversine x 1.4 was
    the primary path. It is still exactly what a degraded hour produces.
    """
    result = haversine_fallback(*KORAMANGALA, *WHITEFIELD)
    assert result.distance_m == 19787
    assert result.source is DistanceSource.haversine
    # 19787m at the flat 20km/h the old eta_minutes assumed.
    assert result.duration_s == 59 * 60
