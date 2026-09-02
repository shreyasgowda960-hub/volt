from datetime import timedelta

import pytest
from sqlalchemy import delete, select, update

from app.database import SessionLocal
from app.models.booking import Booking, BookingStatus
from app.models.user import User
from app.schemas.booking import BookingCreate, LocationIn
from app.services.booking import (
    create_booking,
    expire_stale_bookings,
    reset_expiry_throttle,
)

_PICKUP = LocationIn(address="Koramangala", lat=12.9352, lng=77.6245)
_DROP = LocationIn(address="Whitefield", lat=12.9698, lng=77.75)
_PAYLOAD = BookingCreate(
    pickup=_PICKUP,
    drop=_DROP,
    vehicle_type_code="bike",
    goods_description="Parcel",
    approx_weight_kg=5,
)


async def _make_booking(db, phone: str) -> Booking:
    await db.execute(delete(User).where(User.phone == phone))
    await db.commit()
    user = User(phone=phone)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return await create_booking(db, _PAYLOAD, user)


async def _backdate(db, booking_id: int, minutes: int) -> None:
    """Bookings are created with the DB's now(); back-date created_at
    directly so age-based expiry has something to actually test against."""
    await db.execute(
        update(Booking)
        .where(Booking.id == booking_id)
        .values(created_at=Booking.created_at - timedelta(minutes=minutes))
    )
    await db.commit()


async def _cleanup(db, phone: str) -> None:
    user_id = (
        await db.execute(select(User.id).where(User.phone == phone))
    ).scalar_one_or_none()
    if user_id is not None:
        # Bookings reference users.id; must go first or the FK blocks it.
        await db.execute(delete(Booking).where(Booking.customer_id == user_id))
        await db.execute(delete(User).where(User.id == user_id))
    await db.commit()


@pytest.mark.asyncio
async def test_pending_booking_older_than_five_minutes_expires():
    phone = "+919000004001"
    async with SessionLocal() as db:
        await _cleanup(db, phone)
        booking = await _make_booking(db, phone)
        await _backdate(db, booking.id, minutes=6)

        count = await expire_stale_bookings(db)
        assert count >= 1

        await db.refresh(booking)
        assert booking.status == BookingStatus.expired
        assert booking.expired_at is not None

        await _cleanup(db, phone)


@pytest.mark.asyncio
async def test_pending_booking_under_five_minutes_is_untouched():
    phone = "+919000004002"
    async with SessionLocal() as db:
        await _cleanup(db, phone)
        booking = await _make_booking(db, phone)
        await _backdate(db, booking.id, minutes=4)

        await expire_stale_bookings(db)

        await db.refresh(booking)
        assert booking.status == BookingStatus.pending
        assert booking.expired_at is None

        await _cleanup(db, phone)


@pytest.mark.asyncio
async def test_driver_assigned_booking_is_never_expired_even_if_old():
    phone = "+919000004003"
    async with SessionLocal() as db:
        await _cleanup(db, phone)
        booking = await _make_booking(db, phone)
        await _backdate(db, booking.id, minutes=30)
        await db.execute(
            update(Booking)
            .where(Booking.id == booking.id)
            .values(status=BookingStatus.driver_assigned)
        )
        await db.commit()

        await expire_stale_bookings(db)

        await db.refresh(booking)
        assert booking.status == BookingStatus.driver_assigned
        assert booking.expired_at is None

        await _cleanup(db, phone)


@pytest.mark.asyncio
async def test_sweep_is_throttled_within_the_interval():
    """The sweep must not run a write transaction on every request.

    Polling made this matter: at a 5s interval each open screen dragged a
    sweep along behind every request, roughly 12 a minute per active user,
    almost all matching zero rows.

    Backdates a booking far enough to be expirable, sweeps once, then creates
    a second expirable booking and sweeps again immediately. The second call
    must be suppressed and leave that booking pending.
    """
    phone_a = "+919000004101"
    phone_b = "+919000004102"
    async with SessionLocal() as db:
        await _cleanup(db, phone_a)
        await _cleanup(db, phone_b)

        first = await _make_booking(db, phone_a)
        await _backdate(db, first.id, 10)

        swept = await expire_stale_bookings(db)
        assert swept == 1

        # Second booking, equally stale, but within the throttle window.
        second = await _make_booking(db, phone_b)
        await _backdate(db, second.id, 10)

        suppressed = await expire_stale_bookings(db)
        assert suppressed == 0

        still_pending = (
            await db.execute(select(Booking.status).where(Booking.id == second.id))
        ).scalar_one()
        assert still_pending == BookingStatus.pending

        # Clearing the throttle is all that stands between it and expiry —
        # proves the booking really was expirable and the throttle, not the
        # WHERE clause, is what spared it.
        reset_expiry_throttle()
        assert await expire_stale_bookings(db) == 1

        await _cleanup(db, phone_a)
        await _cleanup(db, phone_b)
