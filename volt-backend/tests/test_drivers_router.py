from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.main import app
from app.models.booking import Booking
from app.models.driver import Driver
from app.models.user import User

_REGISTER_PAYLOAD = {
    "name": "Test Driver",
    "vehicle_number": "KA 05 AB 9999",
    "vehicle_type_code": "bike",
}

_BOOKING_PAYLOAD = {
    "pickup": {"address": "Koramangala", "lat": 12.9352, "lng": 77.6245},
    "drop": {"address": "Whitefield", "lat": 12.9698, "lng": 77.75},
    "vehicle_type_code": "bike",
    "goods_description": "Test parcel",
    "approx_weight_kg": 5,
    "payment_method": "cash",
}

_AUTH_HEADERS = {"Authorization": "Bearer whatever"}


def _mock_token(uid: str, phone: str):
    return patch(
        "app.auth.firebase_auth.verify_id_token",
        return_value={"uid": uid, "phone_number": phone},
    )


async def _cleanup_driver(phone: str) -> None:
    async with SessionLocal() as db:
        driver_id = (
            await db.execute(select(Driver.id).where(Driver.phone == phone))
        ).scalar_one_or_none()
        if driver_id is not None:
            # Bookings reference drivers.id once accepted; must go first or
            # the FK blocks deleting the driver.
            await db.execute(delete(Booking).where(Booking.driver_id == driver_id))
            await db.execute(delete(Driver).where(Driver.id == driver_id))
        await db.commit()


async def _cleanup_user(phone: str) -> None:
    async with SessionLocal() as db:
        user_id = (
            await db.execute(select(User.id).where(User.phone == phone))
        ).scalar_one_or_none()
        if user_id is not None:
            await db.execute(delete(Booking).where(Booking.customer_id == user_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()


@pytest.mark.asyncio
async def test_register_creates_verified_offline_driver():
    phone = "+919000007001"
    await _cleanup_driver(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-reg-1", phone):
            resp = await client.post(
                "/api/v1/drivers/register",
                json=_REGISTER_PAYLOAD,
                headers=_AUTH_HEADERS,
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["is_verified"] is True
    assert data["is_online"] is False

    await _cleanup_driver(phone)


@pytest.mark.asyncio
async def test_register_twice_returns_409():
    phone = "+919000007002"
    await _cleanup_driver(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-reg-2", phone):
            first = await client.post(
                "/api/v1/drivers/register",
                json=_REGISTER_PAYLOAD,
                headers=_AUTH_HEADERS,
            )
            second = await client.post(
                "/api/v1/drivers/register",
                json=_REGISTER_PAYLOAD,
                headers=_AUTH_HEADERS,
            )

    assert first.status_code == 201
    assert second.status_code == 409

    await _cleanup_driver(phone)


@pytest.mark.asyncio
async def test_register_unknown_vehicle_type_returns_422():
    phone = "+919000007003"
    await _cleanup_driver(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-reg-3", phone):
            resp = await client.post(
                "/api/v1/drivers/register",
                json={**_REGISTER_PAYLOAD, "vehicle_type_code": "hovercraft"},
                headers=_AUTH_HEADERS,
            )

    assert resp.status_code == 422

    await _cleanup_driver(phone)


@pytest.mark.asyncio
async def test_get_me_without_driver_row_returns_403():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-no-driver-row", "+919000007004"):
            resp = await client.get("/api/v1/drivers/me", headers=_AUTH_HEADERS)

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_availability_toggle_on_and_off():
    phone = "+919000007005"
    await _cleanup_driver(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-avail-1", phone):
            await client.post(
                "/api/v1/drivers/register",
                json=_REGISTER_PAYLOAD,
                headers=_AUTH_HEADERS,
            )
            online = await client.patch(
                "/api/v1/drivers/me/availability",
                json={"is_online": True},
                headers=_AUTH_HEADERS,
            )
            offline = await client.patch(
                "/api/v1/drivers/me/availability",
                json={"is_online": False},
                headers=_AUTH_HEADERS,
            )

    assert online.status_code == 200
    assert online.json()["is_online"] is True
    assert offline.status_code == 200
    assert offline.json()["is_online"] is False

    await _cleanup_driver(phone)


@pytest.mark.asyncio
async def test_going_offline_with_active_booking_returns_409():
    driver_phone = "+919000007006"
    customer_phone = "+919000007106"
    await _cleanup_driver(driver_phone)
    await _cleanup_user(customer_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-avail-active", driver_phone):
            await client.post(
                "/api/v1/drivers/register",
                json=_REGISTER_PAYLOAD,
                headers=_AUTH_HEADERS,
            )
            await client.patch(
                "/api/v1/drivers/me/availability",
                json={"is_online": True},
                headers=_AUTH_HEADERS,
            )

        with _mock_token("uid-avail-customer", customer_phone):
            created = await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )
        code = created.json()["public_code"]

        with _mock_token("uid-avail-active", driver_phone):
            accept = await client.post(
                f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS
            )
            offline_attempt = await client.patch(
                "/api/v1/drivers/me/availability",
                json={"is_online": False},
                headers=_AUTH_HEADERS,
            )

    assert accept.status_code == 200
    assert offline_attempt.status_code == 409
    assert code in offline_attempt.json()["detail"]

    await _cleanup_driver(driver_phone)
    await _cleanup_user(customer_phone)


@pytest.mark.asyncio
async def test_jobs_requires_online_and_filters_by_vehicle_type():
    driver_phone = "+919000007007"
    other_driver_phone = "+919000007207"
    customer_phone = "+919000007107"
    await _cleanup_driver(driver_phone)
    await _cleanup_driver(other_driver_phone)
    await _cleanup_user(customer_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-jobs-offline", driver_phone):
            await client.post(
                "/api/v1/drivers/register",
                json=_REGISTER_PAYLOAD,
                headers=_AUTH_HEADERS,
            )
            offline_jobs = await client.get(
                "/api/v1/drivers/jobs", headers=_AUTH_HEADERS
            )

        with _mock_token("uid-jobs-customer", customer_phone):
            created = await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )
            # A mini-truck booking should never show up for a bike driver.
            await client.post(
                "/api/v1/bookings",
                json={**_BOOKING_PAYLOAD, "vehicle_type_code": "mini_truck"},
                headers=_AUTH_HEADERS,
            )
        bike_code = created.json()["public_code"]

        with _mock_token("uid-jobs-offline", driver_phone):
            await client.patch(
                "/api/v1/drivers/me/availability",
                json={"is_online": True},
                headers=_AUTH_HEADERS,
            )
            online_jobs = await client.get(
                "/api/v1/drivers/jobs", headers=_AUTH_HEADERS
            )

    assert offline_jobs.status_code == 403

    assert online_jobs.status_code == 200
    codes = [b["public_code"] for b in online_jobs.json()]
    assert bike_code in codes
    assert all(b["vehicle_type_code"] == "bike" for b in online_jobs.json())

    await _cleanup_driver(driver_phone)
    await _cleanup_driver(other_driver_phone)
    await _cleanup_user(customer_phone)
