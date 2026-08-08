from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.main import app
from app.models.booking import Booking
from app.models.user import User

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
async def test_list_bookings_returns_only_callers_bookings():
    phone_a = "+919000000201"
    phone_b = "+919000000202"
    await _cleanup_user(phone_a)
    await _cleanup_user(phone_b)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-list-a", phone_a):
            create_a = await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )
        with _mock_token("uid-list-b", phone_b):
            await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )

        with _mock_token("uid-list-a", phone_a):
            resp = await client.get("/api/v1/bookings", headers=_AUTH_HEADERS)

    assert create_a.status_code == 201
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["public_code"] == create_a.json()["public_code"]

    await _cleanup_user(phone_a)
    await _cleanup_user(phone_b)


@pytest.mark.asyncio
async def test_list_bookings_respects_limit_and_orders_newest_first():
    phone = "+919000000203"
    await _cleanup_user(phone)

    transport = ASGITransport(app=app)
    created_codes = []
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-list-limit", phone):
            for _ in range(3):
                created = await client.post(
                    "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
                )
                assert created.status_code == 201
                created_codes.append(created.json()["public_code"])

            resp = await client.get(
                "/api/v1/bookings", params={"limit": 2}, headers=_AUTH_HEADERS
            )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    # Newest first: the two most recently created, most-recent first.
    assert [b["public_code"] for b in data] == list(reversed(created_codes))[:2]

    await _cleanup_user(phone)


@pytest.mark.asyncio
async def test_list_bookings_without_token_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/bookings")

    assert resp.status_code == 401
