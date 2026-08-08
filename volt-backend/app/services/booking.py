from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking, BookingStatus
from app.models.user import User
from app.schemas.booking import BookingCreate
from app.services.fare import VehicleCapacityExceeded, _fare_paise, load_vehicle_type
from app.utils.codes import generate_public_code
from app.utils.distance import eta_minutes, road_distance_m


async def _unique_public_code(db: AsyncSession) -> str:
    for _ in range(5):
        code = generate_public_code()
        existing = await db.execute(
            select(Booking.id).where(Booking.public_code == code)
        )
        if existing.scalar_one_or_none() is None:
            return code
    raise RuntimeError("could not generate a unique booking code")


async def create_booking(
    db: AsyncSession, payload: BookingCreate, user: User
) -> Booking:
    vehicle = await load_vehicle_type(db, payload.vehicle_type_code)
    if payload.approx_weight_kg > vehicle.capacity_kg:
        raise VehicleCapacityExceeded(payload.approx_weight_kg, vehicle)

    distance_m = road_distance_m(
        payload.pickup.lat,
        payload.pickup.lng,
        payload.drop.lat,
        payload.drop.lng,
    )

    booking = Booking(
        public_code=await _unique_public_code(db),
        customer_id=user.id,
        vehicle_type_code=vehicle.code,
        status=BookingStatus.pending,
        pickup_address=payload.pickup.address,
        pickup_lat=payload.pickup.lat,
        pickup_lng=payload.pickup.lng,
        drop_address=payload.drop.address,
        drop_lat=payload.drop.lat,
        drop_lng=payload.drop.lng,
        goods_description=payload.goods_description,
        approx_weight_kg=payload.approx_weight_kg,
        quoted_fare_paise=_fare_paise(vehicle, distance_m),
        quoted_distance_m=distance_m,
        quoted_eta_minutes=eta_minutes(distance_m),
        # Rate snapshot: changing vehicle_types next month must never rewrite
        # what this booking was quoted.
        quoted_base_fare_paise=vehicle.base_fare_paise,
        quoted_included_km=vehicle.included_km,
        quoted_per_km_paise=vehicle.per_km_paise,
        quoted_min_fare_paise=vehicle.min_fare_paise,
        payment_method=payload.payment_method,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    return booking


async def get_booking_by_code(
    db: AsyncSession, public_code: str
) -> Booking | None:
    result = await db.execute(
        select(Booking).where(Booking.public_code == public_code)
    )
    return result.scalar_one_or_none()


async def list_bookings_for_user(
    db: AsyncSession, customer_id: int, limit: int
) -> list[Booking]:
    result = await db.execute(
        select(Booking)
        .where(Booking.customer_id == customer_id)
        .order_by(Booking.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
