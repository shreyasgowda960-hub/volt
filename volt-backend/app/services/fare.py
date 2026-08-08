from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_type import VehicleType
from app.schemas.booking import FareOption
from app.utils.distance import eta_minutes, road_distance_m


class VehicleTypeNotFound(Exception):
    pass


class VehicleCapacityExceeded(Exception):
    def __init__(self, approx_weight_kg: float, vehicle: VehicleType):
        self.approx_weight_kg = approx_weight_kg
        self.vehicle = vehicle
        super().__init__(
            f"{approx_weight_kg}kg exceeds {vehicle.label}'s "
            f"{vehicle.capacity_kg}kg capacity"
        )


def _fare_paise(vehicle: VehicleType, distance_m: int) -> int:
    """base + (billable km x per-km rate), floored at the minimum fare.

    Integer arithmetic, not Decimal: included_km, per_km_paise etc. come out
    of Postgres as float (Numeric columns use asdecimal=False — see spec 003),
    and distance is already an integer count of metres. Working entirely in
    metres/paise avoids float rounding without needing Decimal at all.
    """
    included_m = round(vehicle.included_km * 1000)
    billable_m = max(0, distance_m - included_m)
    raw = vehicle.base_fare_paise + (billable_m * vehicle.per_km_paise) // 1000
    return max(raw, vehicle.min_fare_paise)


async def load_active_vehicle_types(db: AsyncSession) -> list[VehicleType]:
    result = await db.execute(
        select(VehicleType)
        .where(VehicleType.is_active.is_(True))
        .order_by(VehicleType.sort_order)
    )
    return list(result.scalars().all())


async def load_vehicle_type(db: AsyncSession, code: str) -> VehicleType:
    vehicle = await db.get(VehicleType, code)
    if vehicle is None or not vehicle.is_active:
        raise VehicleTypeNotFound(code)
    return vehicle


def _filter_by_capacity(
    vehicles: list[VehicleType], approx_weight_kg: float | None
) -> list[VehicleType]:
    if approx_weight_kg is None:
        return vehicles
    return [v for v in vehicles if v.capacity_kg >= approx_weight_kg]


async def estimate_all(
    db: AsyncSession,
    pickup_lat: float,
    pickup_lng: float,
    drop_lat: float,
    drop_lng: float,
    approx_weight_kg: float | None = None,
) -> tuple[int, int, list[FareOption]]:
    """Returns (distance_m, eta_minutes, options)."""
    distance_m = road_distance_m(pickup_lat, pickup_lng, drop_lat, drop_lng)
    eta = eta_minutes(distance_m)

    vehicles = _filter_by_capacity(await load_active_vehicle_types(db), approx_weight_kg)
    options = [
        FareOption(
            vehicle_type_code=v.code,
            label=v.label,
            capacity_kg=v.capacity_kg,
            fare_paise=_fare_paise(v, distance_m),
            distance_m=distance_m,
            eta_minutes=eta,
        )
        for v in vehicles
    ]
    return distance_m, eta, options
