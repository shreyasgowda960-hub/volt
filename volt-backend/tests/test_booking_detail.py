"""Spec 011 — BookingDetailResponse: driver details, eager loading, and the
one-directional contact rule.

The privacy assertions here are deliberately tests rather than conventions.
"Drivers must not receive customer data" and "the driver's number disappears
once the trip ends" are both one careless field addition away from being
untrue, and neither would show up as a broken feature.
"""

import asyncio
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, event, select

from app.database import SessionLocal, engine
from app.main import app
from app.models.booking import Booking
from app.models.driver import Driver
from app.models.user import User
from app.schemas.booking import BookingResponse

_BOOKING_PAYLOAD = {
    "pickup": {"address": "Koramangala", "lat": 12.9352, "lng": 77.6245},
    "drop": {"address": "Whitefield", "lat": 12.9698, "lng": 77.75},
    "vehicle_type_code": "bike",
    "goods_description": "Test parcel",
    "approx_weight_kg": 5,
    "payment_method": "cash",
}

_AUTH_HEADERS = {"Authorization": "Bearer whatever"}

_DRIVER_PAYLOAD = {
    "name": "Detail Test Driver",
    "vehicle_number": "KA 05 DT 4242",
    "vehicle_type_code": "bike",
}


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


async def _cleanup_driver(phone: str) -> None:
    async with SessionLocal() as db:
        driver_id = (
            await db.execute(select(Driver.id).where(Driver.phone == phone))
        ).scalar_one_or_none()
        if driver_id is not None:
            # Bookings hold drivers.id once accepted; FK blocks the reverse order.
            await db.execute(delete(Booking).where(Booking.driver_id == driver_id))
            await db.execute(delete(Driver).where(Driver.id == driver_id))
        await db.commit()


async def _register_and_go_online(client, phone: str, uid: str) -> None:
    with _mock_token(uid, phone):
        await client.post(
            "/api/v1/drivers/register", json=_DRIVER_PAYLOAD, headers=_AUTH_HEADERS
        )
        await client.patch(
            "/api/v1/drivers/me/availability",
            json={"is_online": True},
            headers=_AUTH_HEADERS,
        )


async def _create_booking(client, uid: str, phone: str) -> str:
    with _mock_token(uid, phone):
        created = await client.post(
            "/api/v1/bookings", json=_BOOKING_PAYLOAD, headers=_AUTH_HEADERS
        )
    assert created.status_code == 201
    return created.json()["public_code"]


async def _get_detail(client, uid: str, phone: str, code: str) -> dict:
    with _mock_token(uid, phone):
        resp = await client.get(f"/api/v1/bookings/{code}", headers=_AUTH_HEADERS)
    assert resp.status_code == 200
    return resp.json()


@contextmanager
def _count_queries():
    """Counts statements actually sent to the database.

    Hooks before_cursor_execute on engine.sync_engine — the AsyncEngine wraps
    a sync one, and that is where SQLAlchemy's events live. The count includes
    unrelated statements (auth's user lookup, the lazy-expiry UPDATE, BEGIN),
    so no test here asserts an absolute number. What they assert is that the
    count does not grow with the number of rows returned, which is the actual
    definition of "no N+1" and is immune to those extras.
    """
    counter = {"n": 0}

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(engine.sync_engine, "before_cursor_execute", _on_execute)
    try:
        yield counter
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on_execute)


@pytest.mark.asyncio
async def test_driver_is_null_while_unassigned():
    customer_phone = "+919000011001"
    await _cleanup_user(customer_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        code = await _create_booking(client, "uid-detail-c1", customer_phone)
        body = await _get_detail(client, "uid-detail-c1", customer_phone, code)

    assert body["status"] == "pending"
    # Present as an explicit null, not absent, and not a placeholder object.
    assert "driver" in body
    assert body["driver"] is None
    assert body["driver_assigned_at"] is None

    await _cleanup_user(customer_phone)


@pytest.mark.asyncio
async def test_driver_details_present_once_assigned():
    customer_phone = "+919000011002"
    driver_phone = "+919000011102"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_and_go_online(client, driver_phone, "uid-detail-d2")
        code = await _create_booking(client, "uid-detail-c2", customer_phone)

        with _mock_token("uid-detail-d2", driver_phone):
            accept = await client.post(
                f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS
            )
        assert accept.status_code == 200

        body = await _get_detail(client, "uid-detail-c2", customer_phone, code)

    assert body["status"] == "driver_assigned"
    assert body["driver_assigned_at"] is not None
    driver = body["driver"]
    assert driver is not None
    assert driver["name"] == _DRIVER_PAYLOAD["name"]
    assert driver["vehicle_number"] == _DRIVER_PAYLOAD["vehicle_number"]
    assert driver["vehicle_type_code"] == "bike"
    # The number is the point of the whole schema while the trip is live.
    assert driver["phone"] == driver_phone

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)


@pytest.mark.asyncio
async def test_driver_phone_hidden_once_delivered():
    customer_phone = "+919000011003"
    driver_phone = "+919000011103"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_and_go_online(client, driver_phone, "uid-detail-d3")
        code = await _create_booking(client, "uid-detail-c3", customer_phone)

        with _mock_token("uid-detail-d3", driver_phone):
            await client.post(f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS)
            await client.post(f"/api/v1/bookings/{code}/pickup", headers=_AUTH_HEADERS)
            await client.post(f"/api/v1/bookings/{code}/deliver", headers=_AUTH_HEADERS)

        body = await _get_detail(client, "uid-detail-c3", customer_phone, code)

    assert body["status"] == "delivered"
    assert body["delivered_at"] is not None
    driver = body["driver"]
    # Who did the delivery stays visible; how to phone them does not.
    assert driver is not None
    assert driver["name"] == _DRIVER_PAYLOAD["name"]
    assert driver["vehicle_number"] == _DRIVER_PAYLOAD["vehicle_number"]
    assert driver["phone"] is None

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)


@pytest.mark.asyncio
async def test_driver_phone_hidden_when_cancelled_after_assignment():
    """The case the rule exists for.

    A customer whose driver was already assigned can see who cancelled on
    them, because that is their business. They cannot get the number — an
    aggrieved customer ringing a driver about a cancellation is the channel
    this deliberately does not open. Disputes go through support.
    """
    customer_phone = "+919000011004"
    driver_phone = "+919000011104"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_and_go_online(client, driver_phone, "uid-detail-d4")
        code = await _create_booking(client, "uid-detail-c4", customer_phone)

        with _mock_token("uid-detail-d4", driver_phone):
            await client.post(f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS)

        with _mock_token("uid-detail-c4", customer_phone):
            cancel = await client.post(
                f"/api/v1/bookings/{code}/cancel",
                json={"cancellation_reason": "Changed my mind"},
                headers=_AUTH_HEADERS,
            )
        assert cancel.status_code == 200

        body = await _get_detail(client, "uid-detail-c4", customer_phone, code)

    assert body["status"] == "cancelled"
    assert body["cancelled_at"] is not None
    assert body["cancelled_by"] == "customer"
    assert body["cancellation_reason"] == "Changed my mind"
    driver = body["driver"]
    assert driver is not None
    assert driver["name"] == _DRIVER_PAYLOAD["name"]
    assert driver["vehicle_number"] == _DRIVER_PAYLOAD["vehicle_number"]
    assert driver["phone"] is None

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)


@pytest.mark.asyncio
async def test_list_bookings_loads_drivers_without_n_plus_one():
    """Query count must not grow with the number of bookings returned.

    Each assigned booking gets a DIFFERENT driver, and that detail is the
    whole test. An earlier version of this reused one driver for every
    booking and passed even with the relationship deliberately set to
    lazy="immediate" and the selectinload removed — the session's identity
    map already held that single driver, so the repeats cost nothing and the
    assertion was measuring nothing. Distinct drivers are what force a
    per-row strategy to actually emit per-row queries.

    With selectinload the driver rows arrive in one extra statement whatever
    the row count; with a per-object strategy it is one statement per
    assigned booking.
    """
    customer_phone = "+919000011005"
    driver_phones = ["+919000011105", "+919000011205", "+919000011305"]
    await _cleanup_user(customer_phone)
    for phone in driver_phones:
        await _cleanup_driver(phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First driver, first booking — the one-booking baseline.
        await _register_and_go_online(client, driver_phones[0], "uid-detail-d5a")
        first_code = await _create_booking(client, "uid-detail-c5", customer_phone)
        with _mock_token("uid-detail-d5a", driver_phones[0]):
            accept = await client.post(
                f"/api/v1/bookings/{first_code}/accept", headers=_AUTH_HEADERS
            )
        assert accept.status_code == 200

        with _mock_token("uid-detail-c5", customer_phone):
            with _count_queries() as one_booking:
                resp_one = await client.get("/api/v1/bookings", headers=_AUTH_HEADERS)
        assert resp_one.status_code == 200
        assert len(resp_one.json()) == 1

        # Two more bookings, each claimed by its own driver, plus one pending.
        for i, phone in enumerate(driver_phones[1:], start=1):
            uid = f"uid-detail-d5{chr(ord('a') + i)}"
            await _register_and_go_online(client, phone, uid)
            code = await _create_booking(client, "uid-detail-c5", customer_phone)
            with _mock_token(uid, phone):
                claimed = await client.post(
                    f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS
                )
            assert claimed.status_code == 200
        await _create_booking(client, "uid-detail-c5", customer_phone)

        with _mock_token("uid-detail-c5", customer_phone):
            with _count_queries() as four_bookings:
                resp_four = await client.get("/api/v1/bookings", headers=_AUTH_HEADERS)

    assert resp_four.status_code == 200
    bodies = resp_four.json()
    assert len(bodies) == 4

    # Driver populated exactly where one is assigned, and they are distinct.
    assigned = [b for b in bodies if b["status"] == "driver_assigned"]
    pending = [b for b in bodies if b["status"] == "pending"]
    assert len(assigned) == 3
    assert len(pending) == 1
    assert all(b["driver"] is not None for b in assigned)
    assert pending[0]["driver"] is None
    assert len({b["driver"]["phone"] for b in assigned}) == 3

    # The assertion this test exists for: four bookings across three drivers
    # cost the same number of statements as one booking with one driver.
    assert four_bookings["n"] == one_booking["n"], (
        f"query count grew from {one_booking['n']} (1 booking, 1 driver) to "
        f"{four_bookings['n']} (4 bookings, 3 drivers) — driver is not being "
        "eager-loaded in one batch"
    )

    await _cleanup_user(customer_phone)
    for phone in driver_phones:
        await _cleanup_driver(phone)


@pytest.mark.asyncio
async def test_driver_facing_responses_carry_no_extra_fields():
    """The privacy guarantee, asserted on absence.

    Both driver endpoints must return exactly BookingResponse's fields — no
    `driver`, no customer contact details, nothing that arrived by someone
    widening a shared schema. Comparing the whole key set (rather than
    checking a handful of names) is what makes this catch a field nobody
    thought to look for.
    """
    customer_phone = "+919000011006"
    driver_phone = "+919000011106"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)

    expected_keys = set(BookingResponse.model_fields)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_and_go_online(client, driver_phone, "uid-detail-d6")
        code = await _create_booking(client, "uid-detail-c6", customer_phone)

        with _mock_token("uid-detail-d6", driver_phone):
            jobs = await client.get("/api/v1/drivers/jobs", headers=_AUTH_HEADERS)
            assert jobs.status_code == 200
            job = next(j for j in jobs.json() if j["public_code"] == code)
            assert set(job) == expected_keys
            assert "driver" not in job

            await client.post(f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS)

            mine = await client.get("/api/v1/drivers/bookings", headers=_AUTH_HEADERS)
            assert mine.status_code == 200
            held = next(b for b in mine.json() if b["public_code"] == code)
            # Checked after accepting too: this row has a driver_id, so it is
            # the one where an accidental `driver` field would actually show up.
            assert set(held) == expected_keys
            assert "driver" not in held

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)


# --- Refusals: plain language, and idempotent where the intent is met ---


async def _timestamps(client, uid: str, phone: str, code: str) -> dict:
    """Lifecycle timestamps as the customer endpoint reports them.

    Read through the API rather than the DB on purpose: BookingDetailResponse
    is where these are actually observable, so this checks the thing a caller
    can see.
    """
    body = await _get_detail(client, uid, phone, code)
    return {
        "picked_up_at": body["picked_up_at"],
        "delivered_at": body["delivered_at"],
        "cancelled_at": body["cancelled_at"],
    }


@pytest.mark.asyncio
async def test_repeated_pickup_is_idempotent_and_does_not_restamp():
    """A second pickup is success, not a conflict.

    The reported bug was the 409 this used to return, whose detail read
    "Cannot move booking from BookingStatus.picked_up to
    BookingStatus.picked_up". The driver asked for the booking to be picked
    up and it is, so 200 with the existing row is the honest answer.

    The timestamp assertion is the important half: picked_up_at is the record
    of when goods actually changed hands, and a retry must never move it. The
    sleep guarantees a re-stamp would be visible — func.now() is transaction
    start time, so two transactions 50ms apart get different values.
    """
    customer_phone = "+919000011007"
    driver_phone = "+919000011107"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_and_go_online(client, driver_phone, "uid-detail-d7")
        code = await _create_booking(client, "uid-detail-c7", customer_phone)

        with _mock_token("uid-detail-d7", driver_phone):
            await client.post(f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS)
            first = await client.post(
                f"/api/v1/bookings/{code}/pickup", headers=_AUTH_HEADERS
            )
        before = await _timestamps(client, "uid-detail-c7", customer_phone, code)

        await asyncio.sleep(0.05)

        with _mock_token("uid-detail-d7", driver_phone):
            second = await client.post(
                f"/api/v1/bookings/{code}/pickup", headers=_AUTH_HEADERS
            )
        after = await _timestamps(client, "uid-detail-c7", customer_phone, code)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "picked_up"
    assert second.json()["public_code"] == code
    assert before["picked_up_at"] is not None
    assert after["picked_up_at"] == before["picked_up_at"]

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)


@pytest.mark.asyncio
async def test_repeated_deliver_is_idempotent_and_does_not_restamp():
    customer_phone = "+919000011008"
    driver_phone = "+919000011108"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_and_go_online(client, driver_phone, "uid-detail-d8")
        code = await _create_booking(client, "uid-detail-c8", customer_phone)

        with _mock_token("uid-detail-d8", driver_phone):
            await client.post(f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS)
            await client.post(f"/api/v1/bookings/{code}/pickup", headers=_AUTH_HEADERS)
            await client.post(f"/api/v1/bookings/{code}/deliver", headers=_AUTH_HEADERS)
        before = await _timestamps(client, "uid-detail-c8", customer_phone, code)

        await asyncio.sleep(0.05)

        with _mock_token("uid-detail-d8", driver_phone):
            second = await client.post(
                f"/api/v1/bookings/{code}/deliver", headers=_AUTH_HEADERS
            )
        after = await _timestamps(client, "uid-detail-c8", customer_phone, code)

    assert second.status_code == 200
    assert second.json()["status"] == "delivered"
    assert before["delivered_at"] is not None
    assert after["delivered_at"] == before["delivered_at"]

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)


@pytest.mark.asyncio
async def test_repeated_cancel_is_idempotent_and_does_not_restamp():
    customer_phone = "+919000011009"
    await _cleanup_user(customer_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        code = await _create_booking(client, "uid-detail-c9", customer_phone)

        with _mock_token("uid-detail-c9", customer_phone):
            first = await client.post(
                f"/api/v1/bookings/{code}/cancel",
                json={"cancellation_reason": "Changed my mind"},
                headers=_AUTH_HEADERS,
            )
        before = await _timestamps(client, "uid-detail-c9", customer_phone, code)

        await asyncio.sleep(0.05)

        with _mock_token("uid-detail-c9", customer_phone):
            # Different reason on the retry. It must NOT overwrite the
            # original, because no write happens on the idempotent path.
            second = await client.post(
                f"/api/v1/bookings/{code}/cancel",
                json={"cancellation_reason": "Second thoughts"},
                headers=_AUTH_HEADERS,
            )
        after = await _get_detail(client, "uid-detail-c9", customer_phone, code)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "cancelled"
    assert after["cancelled_at"] == before["cancelled_at"]
    assert after["cancellation_reason"] == "Changed my mind"

    await _cleanup_user(customer_phone)


@pytest.mark.asyncio
async def test_genuine_illegal_transitions_still_conflict_in_plain_language():
    """Idempotency covers only "already in the state you asked for".

    Everything else is still a 409, and none of those details may carry a
    Python enum repr. Asserted on absence, because a nicer message that still
    interpolates an enum member somewhere would read fine in one case and
    leak in the next.
    """
    customer_phone = "+919000011010"
    driver_phone = "+919000011110"
    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _register_and_go_online(client, driver_phone, "uid-detail-d10")
        code = await _create_booking(client, "uid-detail-c10", customer_phone)

        with _mock_token("uid-detail-d10", driver_phone):
            await client.post(f"/api/v1/bookings/{code}/accept", headers=_AUTH_HEADERS)
            # Deliver before pickup: not the target state, so still refused.
            early_deliver = await client.post(
                f"/api/v1/bookings/{code}/deliver", headers=_AUTH_HEADERS
            )
            await client.post(f"/api/v1/bookings/{code}/pickup", headers=_AUTH_HEADERS)

        # Cancel after pickup — the one the scope explicitly keeps as 409.
        # Goods are already with the driver; that is a support problem.
        with _mock_token("uid-detail-c10", customer_phone):
            late_cancel = await client.post(
                f"/api/v1/bookings/{code}/cancel", headers=_AUTH_HEADERS
            )

        # And the booking really is still picked_up — the refused cancel
        # changed nothing.
        still = await _get_detail(client, "uid-detail-c10", customer_phone, code)

    assert early_deliver.status_code == 409
    assert early_deliver.json()["detail"] == "This booking has not been picked up yet"

    assert late_cancel.status_code == 409
    assert late_cancel.json()["detail"] == "This booking has already been picked up"

    assert still["status"] == "picked_up"
    assert still["cancelled_at"] is None

    for resp in (early_deliver, late_cancel):
        detail = resp.json()["detail"]
        assert "BookingStatus" not in detail
        assert "->" not in detail

    await _cleanup_user(customer_phone)
    await _cleanup_driver(driver_phone)
