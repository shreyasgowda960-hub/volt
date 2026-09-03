"""Spec 012 — the Places/Geocoding proxy and the coordinate cache.

Google is never actually called here: every test either stubs the client or
exercises the paths that run before it. What is being tested is our own
contract — auth, status-code mapping, the session-token/cache rule, and the
retention delete — none of which needs a live key or a billable request.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, update

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models.place_coordinate import PlaceCoordinate
from app.models.user import User
from app.services import place_cache
from app.services.google_maps import (
    GoogleMapsError,
    GoogleMapsNoResult,
    PlaceSuggestion,
    ResolvedPlace,
)

_AUTH_HEADERS = {"Authorization": "Bearer whatever"}

_PLACE_ID = "ChIJtest_koramangala"


def _mock_token(uid: str, phone: str):
    return patch(
        "app.auth.firebase_auth.verify_id_token",
        return_value={"uid": uid, "phone_number": phone},
    )


async def _cleanup_user(phone: str) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(User).where(User.phone == phone))
        await db.commit()


async def _cleanup_cache(*place_ids: str) -> None:
    async with SessionLocal() as db:
        await db.execute(
            delete(PlaceCoordinate).where(PlaceCoordinate.place_id.in_(place_ids))
        )
        await db.commit()


def _with_key(value: str | None = "test-key"):
    """Overrides GOOGLE_MAPS_API_KEY through the settings cache."""
    return patch.dict(
        "os.environ", {"GOOGLE_MAPS_API_KEY": value} if value else {}, clear=False
    )


# --- Authentication -------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/v1/places/autocomplete", {"query": "koramangala", "session_token": "t"}),
        ("/api/v1/places/details", {"place_id": _PLACE_ID}),
        ("/api/v1/places/reverse-geocode", {"lat": 12.97, "lng": 77.59}),
    ],
)
async def test_every_proxy_endpoint_requires_auth(path, body):
    """Unlike /bookings/estimate, which is public by design.

    The difference is who pays. Price discovery costs us a haversine; these
    spend money with Google per call, so an open one is free autocomplete for
    anyone who reads the app's traffic, billed to us.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(path, json=body)

    assert resp.status_code == 401


# --- Missing key ----------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_api_key_returns_503_naming_the_problem():
    """A service that boots fine and then fails cryptically on first use is
    worse than one that says what is wrong. Config absence is a 503, not a
    500 — it is fixed by setting a variable, not by a deploy."""
    phone = "+919000013001"
    await _cleanup_user(phone)

    get_settings.cache_clear()
    try:
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": ""}):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                with _mock_token("uid-places-1", phone):
                    resp = await client.post(
                        "/api/v1/places/autocomplete",
                        json={"query": "koramangala", "session_token": "tok"},
                        headers=_AUTH_HEADERS,
                    )
    finally:
        get_settings.cache_clear()

    assert resp.status_code == 503
    # The customer is told what they can do instead, not what we forgot.
    detail = resp.json()["detail"]
    assert "manually" in detail or "pin" in detail
    assert "GOOGLE_MAPS_API_KEY" not in detail

    await _cleanup_user(phone)


# --- Autocomplete ---------------------------------------------------------


@pytest.mark.asyncio
async def test_autocomplete_maps_google_suggestions_to_our_shape():
    phone = "+919000013002"
    await _cleanup_user(phone)

    stub = [
        PlaceSuggestion(
            place_id=_PLACE_ID,
            description="Koramangala, Bengaluru, Karnataka, India",
            main_text="Koramangala",
            secondary_text="Bengaluru, Karnataka, India",
        )
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-places-2", phone):
            with patch(
                "app.services.google_maps.autocomplete", return_value=stub
            ) as mocked:
                resp = await client.post(
                    "/api/v1/places/autocomplete",
                    json={"query": "koramangala", "session_token": "tok-abc"},
                    headers=_AUTH_HEADERS,
                )

    assert resp.status_code == 200
    assert resp.json() == {
        "suggestions": [
            {
                "place_id": _PLACE_ID,
                "description": "Koramangala, Bengaluru, Karnataka, India",
                "main_text": "Koramangala",
                "secondary_text": "Bengaluru, Karnataka, India",
            }
        ]
    }
    # The session token must reach Google verbatim, or the whole search is
    # billed per keystroke-batch instead of as one session.
    mocked.assert_awaited_once_with("koramangala", "tok-abc")

    await _cleanup_user(phone)


@pytest.mark.asyncio
async def test_autocomplete_rejects_queries_under_three_characters():
    """Matches the client debounce minimum. Every request costs money, and
    one or two characters cannot produce a useful suggestion."""
    phone = "+919000013003"
    await _cleanup_user(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-places-3", phone):
            resp = await client.post(
                "/api/v1/places/autocomplete",
                json={"query": "ko", "session_token": "tok"},
                headers=_AUTH_HEADERS,
            )

    assert resp.status_code == 422

    await _cleanup_user(phone)


@pytest.mark.asyncio
async def test_upstream_failure_becomes_502_without_leaking_googles_message():
    """Google's error text can name quota states and key problems. Those are
    ours to fix and not a customer's to read."""
    phone = "+919000013004"
    await _cleanup_user(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-places-4", phone):
            with patch(
                "app.services.google_maps.autocomplete",
                side_effect=GoogleMapsError(
                    "autocomplete returned 403: API key not authorized, quota exceeded"
                ),
            ):
                resp = await client.post(
                    "/api/v1/places/autocomplete",
                    json={"query": "koramangala", "session_token": "tok"},
                    headers=_AUTH_HEADERS,
                )

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "quota" not in detail.lower()
    assert "API key" not in detail

    await _cleanup_user(phone)


# --- Details, and the session-token/cache rule ----------------------------


@pytest.mark.asyncio
async def test_details_with_session_token_always_calls_google_and_caches():
    """A session token means a live search, and the Place Details call is
    what closes the billing session. Serving that from cache would save one
    Details call and buy several unbundled autocomplete charges."""
    phone = "+919000013005"
    await _cleanup_user(phone)
    await _cleanup_cache(_PLACE_ID)

    resolved = ResolvedPlace(
        place_id=_PLACE_ID,
        address="Koramangala, Bengaluru",
        lat=12.9352,
        lng=77.6245,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-places-5", phone):
            with patch(
                "app.services.google_maps.place_details", return_value=resolved
            ) as mocked:
                first = await client.post(
                    "/api/v1/places/details",
                    json={"place_id": _PLACE_ID, "session_token": "tok-1"},
                    headers=_AUTH_HEADERS,
                )
                # Second identical call, now that the row is cached. It must
                # STILL go to Google, because a token is present.
                second = await client.post(
                    "/api/v1/places/details",
                    json={"place_id": _PLACE_ID, "session_token": "tok-2"},
                    headers=_AUTH_HEADERS,
                )

    assert first.status_code == 200
    assert first.json()["from_cache"] is False
    assert first.json()["address"] == "Koramangala, Bengaluru"
    assert second.json()["from_cache"] is False
    assert mocked.await_count == 2

    # Coordinates were stored on the way through — the write side runs even
    # for live searches, which is what makes the cache worth anything later.
    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(PlaceCoordinate).where(PlaceCoordinate.place_id == _PLACE_ID)
            )
        ).scalar_one()
        assert (row.lat, row.lng) == (12.9352, 77.6245)

    await _cleanup_cache(_PLACE_ID)
    await _cleanup_user(phone)


@pytest.mark.asyncio
async def test_details_without_session_token_serves_coordinates_from_cache():
    """The re-resolve path: no session is open, so a cache hit is a pure
    saving. The address is necessarily absent — the terms do not permit
    caching it — and from_cache says so."""
    phone = "+919000013006"
    await _cleanup_user(phone)
    await _cleanup_cache(_PLACE_ID)

    async with SessionLocal() as db:
        await place_cache.store_coordinates(db, _PLACE_ID, 12.9352, 77.6245)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-places-6", phone):
            with patch("app.services.google_maps.place_details") as mocked:
                resp = await client.post(
                    "/api/v1/places/details",
                    json={"place_id": _PLACE_ID},
                    headers=_AUTH_HEADERS,
                )

    assert resp.status_code == 200
    body = resp.json()
    assert body["from_cache"] is True
    assert (body["lat"], body["lng"]) == (12.9352, 77.6245)
    assert body["address"] == ""
    # The point of the cache: no billable call happened at all.
    mocked.assert_not_awaited()

    await _cleanup_cache(_PLACE_ID)
    await _cleanup_user(phone)


# --- Reverse geocode ------------------------------------------------------


@pytest.mark.asyncio
async def test_reverse_geocode_returns_googles_snapped_coordinates():
    phone = "+919000013007"
    await _cleanup_user(phone)
    await _cleanup_cache("ChIJsnapped")

    # Google snaps to the matched address, which is not exactly where the pin
    # was dropped. Returning its coordinates keeps address and position
    # describing the same point.
    resolved = ResolvedPlace(
        place_id="ChIJsnapped",
        address="80 Feet Road, Koramangala, Bengaluru",
        lat=12.9350,
        lng=77.6240,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-places-7", phone):
            with patch(
                "app.services.google_maps.reverse_geocode", return_value=resolved
            ):
                resp = await client.post(
                    "/api/v1/places/reverse-geocode",
                    json={"lat": 12.9358, "lng": 77.6251},
                    headers=_AUTH_HEADERS,
                )

    assert resp.status_code == 200
    body = resp.json()
    assert body["address"] == "80 Feet Road, Koramangala, Bengaluru"
    assert (body["lat"], body["lng"]) == (12.9350, 77.6240)

    await _cleanup_cache("ChIJsnapped")
    await _cleanup_user(phone)


@pytest.mark.asyncio
async def test_reverse_geocode_with_no_address_is_404_not_502():
    """A pin in a lake is a real answer the customer can act on, not a
    fault to apologise for."""
    phone = "+919000013008"
    await _cleanup_user(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-places-8", phone):
            with patch(
                "app.services.google_maps.reverse_geocode",
                side_effect=GoogleMapsNoResult(12.0, 77.0),
            ):
                resp = await client.post(
                    "/api/v1/places/reverse-geocode",
                    json={"lat": 12.0, "lng": 77.0},
                    headers=_AUTH_HEADERS,
                )

    assert resp.status_code == 404
    assert "moving the pin" in resp.json()["detail"]

    await _cleanup_user(phone)


# --- Retention ------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_actually_deletes_rows_past_the_retention_window():
    """The terms say delete, so this asserts the row is GONE.

    Not merely filtered out of reads: "we ignore stale rows" leaves the data
    sitting in the table, which is the thing the licence forbids. The
    assertion is a row count, not a lookup result.
    """
    fresh_id = "ChIJfresh"
    stale_id = "ChIJstale"
    await _cleanup_cache(fresh_id, stale_id)

    async with SessionLocal() as db:
        await place_cache.store_coordinates(db, fresh_id, 12.97, 77.59)
        await place_cache.store_coordinates(db, stale_id, 12.98, 77.60)
        # Back-date one past the window, using the DB clock.
        await db.execute(
            update(PlaceCoordinate)
            .where(PlaceCoordinate.place_id == stale_id)
            .values(
                cached_at=func.now()
                - timedelta(days=place_cache.RETENTION_DAYS + 1)
            )
        )
        await db.commit()

        # A stale row must never be served even before the sweep runs.
        assert await place_cache.get_coordinates(db, stale_id) is None

        place_cache.reset_purge_throttle()
        deleted = await place_cache.purge_expired(db)
        assert deleted == 1

        remaining = (
            await db.execute(
                select(PlaceCoordinate.place_id).where(
                    PlaceCoordinate.place_id.in_([fresh_id, stale_id])
                )
            )
        ).scalars().all()

    # Gone from the table, not just hidden from reads.
    assert list(remaining) == [fresh_id]

    await _cleanup_cache(fresh_id, stale_id)


@pytest.mark.asyncio
async def test_purge_is_throttled():
    """Runs on every address request, so it is throttled the same way the
    booking expiry sweep is. 30-day retention needs nothing tighter."""
    stale_id = "ChIJstale2"
    await _cleanup_cache(stale_id)

    async with SessionLocal() as db:
        await place_cache.store_coordinates(db, stale_id, 12.98, 77.60)
        await db.execute(
            update(PlaceCoordinate)
            .where(PlaceCoordinate.place_id == stale_id)
            .values(
                cached_at=func.now()
                - timedelta(days=place_cache.RETENTION_DAYS + 1)
            )
        )
        await db.commit()

        place_cache.reset_purge_throttle()
        assert await place_cache.purge_expired(db) == 1

        # Second stale row inside the throttle window: skipped, not swept.
        await place_cache.store_coordinates(db, stale_id, 12.98, 77.60)
        await db.execute(
            update(PlaceCoordinate)
            .where(PlaceCoordinate.place_id == stale_id)
            .values(
                cached_at=func.now()
                - timedelta(days=place_cache.RETENTION_DAYS + 1)
            )
        )
        await db.commit()

        assert await place_cache.purge_expired(db) == 0
        # Clearing the throttle is the only thing standing between it and
        # deletion — proves the throttle, not the predicate, spared it.
        place_cache.reset_purge_throttle()
        assert await place_cache.purge_expired(db) == 1

    await _cleanup_cache(stale_id)


@pytest.mark.asyncio
async def test_store_coordinates_upserts_and_restarts_the_clock():
    """Two requests resolving the same place must not race on the primary
    key, and a genuinely fresh fetch legitimately starts a new window."""
    place_id = "ChIJupsert"
    await _cleanup_cache(place_id)

    async with SessionLocal() as db:
        await place_cache.store_coordinates(db, place_id, 1.0, 2.0)
        await db.execute(
            update(PlaceCoordinate)
            .where(PlaceCoordinate.place_id == place_id)
            .values(cached_at=func.now() - timedelta(days=10))
        )
        await db.commit()

        before = (
            await db.execute(
                select(PlaceCoordinate.cached_at).where(
                    PlaceCoordinate.place_id == place_id
                )
            )
        ).scalar_one()

        # Same id, new coordinates — must update in place, not raise.
        await place_cache.store_coordinates(db, place_id, 3.0, 4.0)

        row = (
            await db.execute(
                select(PlaceCoordinate).where(PlaceCoordinate.place_id == place_id)
            )
        ).scalar_one()

    assert (row.lat, row.lng) == (3.0, 4.0)
    assert row.cached_at > before

    await _cleanup_cache(place_id)
