import pytest
from sqlalchemy import delete

from app.database import SessionLocal
from app.models.booking import Booking
from app.models.user import User
from app.schemas.booking import BookingCreate, LocationIn
from app.services.booking import create_booking
from app.services.fare import VehicleCapacityExceeded

_PICKUP = LocationIn(address="Koramangala", lat=12.9352, lng=77.6245)
_DROP = LocationIn(address="Whitefield", lat=12.9698, lng=77.75)


@pytest.mark.asyncio
async def test_create_booking_rejects_weight_over_vehicle_capacity():
    phone = "+919000000098"
    async with SessionLocal() as db:
        await db.execute(delete(User).where(User.phone == phone))
        await db.commit()

        user = User(phone=phone)
        db.add(user)
        await db.commit()
        await db.refresh(user)

        # Seeded bike capacity is 20kg.
        payload = BookingCreate(
            pickup=_PICKUP,
            drop=_DROP,
            vehicle_type_code="bike",
            goods_description="Anvil",
            approx_weight_kg=25,
        )

        with pytest.raises(VehicleCapacityExceeded) as exc_info:
            await create_booking(db, payload, user)

        assert exc_info.value.approx_weight_kg == 25
        assert exc_info.value.vehicle.capacity_kg == 20
        assert "25" in str(exc_info.value)
        assert "20" in str(exc_info.value)

        await db.execute(delete(User).where(User.phone == phone))
        await db.commit()


@pytest.mark.asyncio
async def test_create_booking_within_capacity_succeeds():
    phone = "+919000000097"
    async with SessionLocal() as db:
        await db.execute(delete(User).where(User.phone == phone))
        await db.commit()

        user = User(phone=phone)
        db.add(user)
        await db.commit()
        await db.refresh(user)

        payload = BookingCreate(
            pickup=_PICKUP,
            drop=_DROP,
            vehicle_type_code="bike",
            goods_description="Envelope",
            approx_weight_kg=5,
        )

        booking = await create_booking(db, payload, user)
        assert booking.vehicle_type_code == "bike"

        await db.execute(delete(Booking).where(Booking.id == booking.id))
        await db.execute(delete(User).where(User.phone == phone))
        await db.commit()
