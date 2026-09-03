"""Spec 012 — service area enforcement, place ids, GET /service-area.

The service-area check is a money and goodwill boundary in both directions:
too loose and a driver is dispatched 40km out on a fare priced for 8, too
tight and a real customer is refused. The boundary case therefore gets its
own test rather than being assumed.
"""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models.booking import Booking
from app.models.user import User
from app.services.service_area import (
    OutsideServiceArea,
    check_within_service_area,
    distance_from_centre_km,
)

_AUTH_HEADERS = {"Authorization": "Bearer whatever"}

# Bengaluru city centre, matching the configured default.
_CENTRE = (12.9716, 77.5946)

# Roughly 6km north of centre — comfortably inside a 25km radius.
_INSIDE = (13.0250, 77.5946)

# Hosur, about 40km south. The spec's own worked example of "too far".
_HOSUR = (12.7409, 77.8253)


def _mock_token(uid: str, phone: str):
    return patch(
        "app.auth.firebase_auth.verify_id_token",
        return_value={"uid": uid, "phone_number": phone},
    )


def _payload(pickup, drop, pickup_place_id=None, drop_place_id=None) -> dict:
    return {
        "pickup": {
            "address": "Pickup",
            "lat": pickup[0],
            "lng": pickup[1],
            **({"place_id": pickup_place_id} if pickup_place_id else {}),
        },
        "drop": {
            "address": "Drop",
            "lat": drop[0],
            "lng": drop[1],
            **({"place_id": drop_place_id} if drop_place_id else {}),
        },
        "vehicle_type_code": "bike",
        "goods_description": "Test parcel",
        "approx_weight_kg": 5,
        "payment_method": "cash",
    }


async def _cleanup_user(phone: str) -> None:
    async with SessionLocal() as db:
        user_id = (
            await db.execute(select(User.id).where(User.phone == phone))
        ).scalar_one_or_none()
        if user_id is not None:
            await db.execute(delete(Booking).where(Booking.customer_id == user_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()


# --- The check itself -----------------------------------------------------


def test_inside_radius_is_accepted():
    check_within_service_area(*_INSIDE, "pickup")  # must not raise


def test_far_location_is_rejected_with_both_distances():
    with pytest.raises(OutsideServiceArea) as excinfo:
        check_within_service_area(*_HOSUR, "drop")

    error = excinfo.value
    assert error.end == "drop"
    assert error.distance_km > 25
    assert error.radius_km == 25.0
    # The message must name which end and roughly how far, so the customer
    # knows which of the two addresses to change.
    assert "Drop location" in error.user_message
    assert "limit 25km" in error.user_message


def test_exactly_on_the_boundary_is_accepted():
    """The boundary belongs to the inside.

    Refusing a booking for being precisely 25.000km out is indefensible, and
    `>=` instead of `>` would do exactly that.

    Sets the radius to the point's own computed distance rather than hunting
    for a coordinate that lands on 25km. An earlier version did hunt, and it
    was worthless: the search necessarily stops just *inside* the boundary,
    so it passed under `>=` as happily as under `>`. Floating point will not
    hand you an exact equality by search — you have to construct it.
    repr() round-trips a float exactly, so the parsed setting is bit-identical
    to the measured distance and the comparison really is on equality.
    """
    lat, lng = _INSIDE
    exact_km = distance_from_centre_km(lat, lng)

    get_settings.cache_clear()
    with patch.dict("os.environ", {"SERVICE_RADIUS_KM": repr(exact_km)}):
        try:
            assert get_settings().service_radius_km == exact_km, (
                "the radius must be bit-identical for this to test equality"
            )
            check_within_service_area(lat, lng, "pickup")  # must not raise
        finally:
            get_settings.cache_clear()


# --- Enforcement on the endpoints ----------------------------------------


@pytest.mark.asyncio
async def test_estimate_rejects_pickup_outside_area():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/bookings/estimate",
            json={
                "pickup": {"address": "Hosur", "lat": _HOSUR[0], "lng": _HOSUR[1]},
                "drop": {"address": "Drop", "lat": _INSIDE[0], "lng": _INSIDE[1]},
            },
        )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail.startswith("Pickup location is outside")
    assert "Drop" not in detail


@pytest.mark.asyncio
async def test_estimate_rejects_drop_outside_area():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/bookings/estimate",
            json={
                "pickup": {"address": "Pickup", "lat": _INSIDE[0], "lng": _INSIDE[1]},
                "drop": {"address": "Hosur", "lat": _HOSUR[0], "lng": _HOSUR[1]},
            },
        )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail.startswith("Drop location is outside")


@pytest.mark.asyncio
async def test_create_booking_rejects_outside_area_and_writes_nothing():
    phone = "+919000012001"
    await _cleanup_user(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-area-1", phone):
            resp = await client.post(
                "/api/v1/bookings",
                json=_payload(_INSIDE, _HOSUR),
                headers=_AUTH_HEADERS,
            )
            listed = await client.get("/api/v1/bookings", headers=_AUTH_HEADERS)

    assert resp.status_code == 422
    assert resp.json()["detail"].startswith("Drop location is outside")
    # Refused before any row was written — the check runs at the top of
    # create_booking, before the Booking is constructed.
    assert listed.json() == []

    await _cleanup_user(phone)


@pytest.mark.asyncio
async def test_booking_inside_area_round_trips_place_ids():
    phone = "+919000012002"
    await _cleanup_user(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-area-2", phone):
            created = await client.post(
                "/api/v1/bookings",
                json=_payload(
                    _CENTRE,
                    _INSIDE,
                    pickup_place_id="ChIJpickup_test_id",
                    drop_place_id="ChIJdrop_test_id",
                ),
                headers=_AUTH_HEADERS,
            )

    assert created.status_code == 201
    code = created.json()["public_code"]

    # Not exposed on any response schema — nothing reads them yet — so the
    # round trip is asserted against the row itself.
    async with SessionLocal() as db:
        row = (
            await db.execute(select(Booking).where(Booking.public_code == code))
        ).scalar_one()
        assert row.pickup_place_id == "ChIJpickup_test_id"
        assert row.drop_place_id == "ChIJdrop_test_id"

    await _cleanup_user(phone)


@pytest.mark.asyncio
async def test_booking_without_place_ids_is_still_accepted():
    """A dropped pin has no place id, and older app builds send none."""
    phone = "+919000012003"
    await _cleanup_user(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-area-3", phone):
            created = await client.post(
                "/api/v1/bookings",
                json=_payload(_CENTRE, _INSIDE),
                headers=_AUTH_HEADERS,
            )

    assert created.status_code == 201
    code = created.json()["public_code"]

    async with SessionLocal() as db:
        row = (
            await db.execute(select(Booking).where(Booking.public_code == code))
        ).scalar_one()
        assert row.pickup_place_id is None
        assert row.drop_place_id is None

    await _cleanup_user(phone)


# --- GET /service-area ----------------------------------------------------


@pytest.mark.asyncio
async def test_service_area_endpoint_is_public_and_reflects_config():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # No Authorization header: the apps need this before sign-in, to
        # centre the map on the first screen.
        resp = await client.get("/api/v1/service-area")

    assert resp.status_code == 200
    settings = get_settings()
    assert resp.json() == {
        "center_lat": settings.service_center_lat,
        "center_lng": settings.service_center_lng,
        "radius_km": settings.service_radius_km,
    }


@pytest.mark.asyncio
async def test_narrowing_the_radius_takes_effect_without_code_changes():
    """The field-testing scenario the config exists for.

    Narrow the radius in the environment and both the endpoint and the
    enforcement must follow — that is the whole reason these are settings
    rather than constants. get_settings is lru_cached, so the cache has to be
    cleared for an override to be seen; that is also true in production, but
    there the process restarts on an env change.
    """
    original = get_settings()
    assert original.service_radius_km == 25.0

    get_settings.cache_clear()
    with patch.dict("os.environ", {"SERVICE_RADIUS_KM": "5"}):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/service-area")
                # _INSIDE is ~6km out: inside the default 25km, outside a 5km
                # radius. Same coordinate, different answer, no code change.
                estimate = await client.post(
                    "/api/v1/bookings/estimate",
                    json={
                        "pickup": {
                            "address": "Pickup",
                            "lat": _INSIDE[0],
                            "lng": _INSIDE[1],
                        },
                        "drop": {
                            "address": "Centre",
                            "lat": _CENTRE[0],
                            "lng": _CENTRE[1],
                        },
                    },
                )

            assert resp.json()["radius_km"] == 5.0
            assert estimate.status_code == 422
            assert "limit 5km" in estimate.json()["detail"]
        finally:
            # Leave the cache holding real settings again, or every later
            # test in this process inherits a 5km radius.
            get_settings.cache_clear()

    assert get_settings().service_radius_km == 25.0
