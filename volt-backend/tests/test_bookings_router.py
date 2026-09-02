from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.main import app
from app.models.booking import Booking, BookingStatus
from app.models.driver import Driver
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


# --- Driver action endpoints (spec 008) --------------------------------

_DRIVER_REGISTER_PAYLOAD = {
    "name": "Action Test Driver",
    "vehicle_number": "KA 05 AB 3333",
    "vehicle_type_code": "bike",
}


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


async def _register_and_go_online(client, phone: str, uid: str) -> None:
    with _mock_token(uid, phone):
        await client.post(
            "/api/v1/drivers/register",
            json=_DRIVER_REGISTER_PAYLOAD,
            headers=_AUTH_HEADERS,
        )
        await client.patch(
            "/api/v1/drivers/me/availability",
            json={"is_online": True},
            headers=_AUTH_HEADERS,
        )


async def _get_booking_row(public_code: str) -> Booking:
    async with SessionLocal() as db:
        result = await db.execute(
            select(Booking).where(Booking.public_code == public_code)
        )
        return result.scalar_one()


@pytest.mark.asyncio
async def test_full_lifecycle_writes_each_transitions_timestamp():
    customer_phone = "+919000008001"
    driver_phone = "+919000008101"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_and_go_online(client, driver_phone, "uid-lifecycle-driver")

        with _mock_token("uid-lifecycle-customer", customer_phone):
            created = await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )
        code = created.json()["public_code"]

        row = await _get_booking_row(code)
        assert row.status == BookingStatus.pending
        assert row.driver_assigned_at is None

        with _mock_token("uid-lifecycle-driver", driver_phone):
            accept = await client.post(
                f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS
            )
            row = await _get_booking_row(code)
            assert accept.status_code == 200
            assert row.status == BookingStatus.driver_assigned
            assert row.driver_assigned_at is not None
            assert row.picked_up_at is None

            pickup = await client.post(
                f"/api/v1/bookings/{code}/pickup", headers=_AUTH_HEADERS
            )
            row = await _get_booking_row(code)
            assert pickup.status_code == 200
            assert row.status == BookingStatus.picked_up
            assert row.picked_up_at is not None
            assert row.delivered_at is None

            deliver = await client.post(
                f"/api/v1/bookings/{code}/deliver", headers=_AUTH_HEADERS
            )
            row = await _get_booking_row(code)
            assert deliver.status_code == 200
            assert row.status == BookingStatus.delivered
            assert row.delivered_at is not None

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)


@pytest.mark.asyncio
async def test_accept_vehicle_type_mismatch_returns_422():
    customer_phone = "+919000008002"
    driver_phone = "+919000008102"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-mismatch-driver", driver_phone):
            await client.post(
                "/api/v1/drivers/register",
                json={**_DRIVER_REGISTER_PAYLOAD, "vehicle_type_code": "mini_truck"},
                headers=_AUTH_HEADERS,
            )
            await client.patch(
                "/api/v1/drivers/me/availability",
                json={"is_online": True},
                headers=_AUTH_HEADERS,
            )

        with _mock_token("uid-mismatch-customer", customer_phone):
            created = await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )
        code = created.json()["public_code"]

        with _mock_token("uid-mismatch-driver", driver_phone):
            resp = await client.post(
                f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS
            )

    assert resp.status_code == 422

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)


@pytest.mark.asyncio
async def test_accept_offline_driver_returns_403():
    customer_phone = "+919000008003"
    driver_phone = "+919000008103"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-offline-driver", driver_phone):
            # Registered but never goes online.
            await client.post(
                "/api/v1/drivers/register",
                json=_DRIVER_REGISTER_PAYLOAD,
                headers=_AUTH_HEADERS,
            )

        with _mock_token("uid-offline-customer", customer_phone):
            created = await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )
        code = created.json()["public_code"]

        with _mock_token("uid-offline-driver", driver_phone):
            resp = await client.post(
                f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS
            )

    assert resp.status_code == 403

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)


@pytest.mark.asyncio
async def test_accept_already_claimed_returns_409():
    customer_phone = "+919000008004"
    driver_a_phone = "+919000008104"
    driver_b_phone = "+919000008204"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_a_phone)
    await _cleanup_driver(driver_b_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_and_go_online(client, driver_a_phone, "uid-claimed-a")
        await _register_and_go_online(client, driver_b_phone, "uid-claimed-b")

        with _mock_token("uid-claimed-customer", customer_phone):
            created = await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )
        code = created.json()["public_code"]

        with _mock_token("uid-claimed-a", driver_a_phone):
            first = await client.post(
                f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS
            )
        with _mock_token("uid-claimed-b", driver_b_phone):
            second = await client.post(
                f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS
            )

    assert first.status_code == 200
    assert second.status_code == 409

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_a_phone)
    await _cleanup_driver(driver_b_phone)


@pytest.mark.asyncio
async def test_pickup_before_accept_is_illegal_returns_409():
    customer_phone = "+919000008005"
    driver_phone = "+919000008105"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_and_go_online(client, driver_phone, "uid-early-pickup")

        with _mock_token("uid-early-pickup-customer", customer_phone):
            created = await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )
        code = created.json()["public_code"]

        # Never accepted — still pending, has no driver.
        with _mock_token("uid-early-pickup", driver_phone):
            resp = await client.post(
                f"/api/v1/bookings/{code}/pickup", headers=_AUTH_HEADERS
            )

    # Not theirs (no driver assigned yet) -> 404, not 409 — same rule as
    # "driver acting on a booking that isn't theirs".
    assert resp.status_code == 404

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)


@pytest.mark.asyncio
async def test_deliver_before_pickup_is_illegal_returns_409():
    customer_phone = "+919000008006"
    driver_phone = "+919000008106"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_and_go_online(client, driver_phone, "uid-early-deliver")

        with _mock_token("uid-early-deliver-customer", customer_phone):
            created = await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )
        code = created.json()["public_code"]

        with _mock_token("uid-early-deliver", driver_phone):
            await client.post(
                f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS
            )
            resp = await client.post(
                f"/api/v1/bookings/{code}/deliver", headers=_AUTH_HEADERS
            )

    assert resp.status_code == 409

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)


@pytest.mark.asyncio
async def test_pickup_by_wrong_driver_returns_404():
    customer_phone = "+919000008007"
    driver_a_phone = "+919000008107"
    driver_b_phone = "+919000008207"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_a_phone)
    await _cleanup_driver(driver_b_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_and_go_online(client, driver_a_phone, "uid-notyours-a")
        await _register_and_go_online(client, driver_b_phone, "uid-notyours-b")

        with _mock_token("uid-notyours-customer", customer_phone):
            created = await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )
        code = created.json()["public_code"]

        with _mock_token("uid-notyours-a", driver_a_phone):
            await client.post(
                f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS
            )

        # B never accepted this one — it's A's booking now.
        with _mock_token("uid-notyours-b", driver_b_phone):
            resp = await client.post(
                f"/api/v1/bookings/{code}/pickup", headers=_AUTH_HEADERS
            )

    assert resp.status_code == 404

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_a_phone)
    await _cleanup_driver(driver_b_phone)


@pytest.mark.asyncio
async def test_cancel_pending_booking_is_free():
    customer_phone = "+919000008008"
    await _cleanup_user(customer_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-cancel-free", customer_phone):
            created = await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )
            code = created.json()["public_code"]
            resp = await client.post(
                f"/api/v1/bookings/{code}/cancel",
                json={"cancellation_reason": "changed my mind"},
                headers=_AUTH_HEADERS,
            )

    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    row = await _get_booking_row(code)
    assert row.cancelled_by.value == "customer"
    assert row.cancellation_reason == "changed my mind"

    await _cleanup_user(customer_phone)


@pytest.mark.asyncio
async def test_cancel_after_pickup_returns_409():
    customer_phone = "+919000008009"
    driver_phone = "+919000008109"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_and_go_online(client, driver_phone, "uid-cancel-late")

        with _mock_token("uid-cancel-late-customer", customer_phone):
            created = await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )
        code = created.json()["public_code"]

        with _mock_token("uid-cancel-late", driver_phone):
            await client.post(
                f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS
            )
            await client.post(
                f"/api/v1/bookings/{code}/pickup", headers=_AUTH_HEADERS
            )

        with _mock_token("uid-cancel-late-customer", customer_phone):
            resp = await client.post(
                f"/api/v1/bookings/{code}/cancel", headers=_AUTH_HEADERS
            )

    assert resp.status_code == 409

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)


@pytest.mark.asyncio
async def test_cancel_by_non_owning_customer_returns_404():
    owner_phone = "+919000008010"
    other_phone = "+919000008210"
    await _cleanup_user(owner_phone)
    await _cleanup_user(other_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with _mock_token("uid-cancel-owner", owner_phone):
            created = await client.post(
                "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
            )
        code = created.json()["public_code"]

        with _mock_token("uid-cancel-other", other_phone):
            resp = await client.post(
                f"/api/v1/bookings/{code}/cancel", headers=_AUTH_HEADERS
            )

    assert resp.status_code == 404

    await _cleanup_user(owner_phone)
    await _cleanup_user(other_phone)
