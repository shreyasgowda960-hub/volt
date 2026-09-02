from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import _bearer, verify_token
from app.database import get_db
from app.driver_auth import get_current_driver
from app.models.booking import Booking, BookingStatus
from app.models.driver import Driver
from app.schemas.booking import BookingResponse
from app.schemas.driver import AvailabilityUpdate, DriverRegister, DriverResponse
from app.services import booking as booking_service
from app.services.fare import VehicleTypeNotFound, load_vehicle_type

router = APIRouter(prefix="/api/v1/drivers", tags=["drivers"])


@router.post(
    "/register",
    response_model=DriverResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_driver(
    payload: DriverRegister,
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> DriverResponse:
    # get_current_driver can't be used here — the driver row doesn't exist
    # yet, and that dependency 403s when it doesn't find one.
    decoded = await verify_token(creds)
    uid = decoded["uid"]
    phone = decoded["phone_number"]

    existing = await db.execute(select(Driver.id).where(Driver.firebase_uid == uid))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Driver already registered for this account",
        )

    try:
        await load_vehicle_type(db, payload.vehicle_type_code)
    except VehicleTypeNotFound:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown vehicle type: {payload.vehicle_type_code}",
        )

    driver = Driver(
        firebase_uid=uid,
        phone=phone,
        name=payload.name,
        vehicle_number=payload.vehicle_number,
        vehicle_type_code=payload.vehicle_type_code,
        # Decision for phase 1 (spec 008): auto-verify on registration.
        # is_verified stays in the schema so a real verification step can
        # flip it later without a migration.
        is_verified=True,
    )
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return DriverResponse.model_validate(driver)


@router.get("/me", response_model=DriverResponse)
async def get_me(driver: Driver = Depends(get_current_driver)) -> DriverResponse:
    return DriverResponse.model_validate(driver)


@router.patch("/me/availability", response_model=DriverResponse)
async def update_availability(
    payload: AvailabilityUpdate,
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverResponse:
    if not payload.is_online and driver.is_online:
        active = await booking_service.get_active_booking_for_driver(db, driver.id)
        if active is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot go offline while booking {active.public_code} "
                    "is in progress"
                ),
            )

    driver.is_online = payload.is_online
    await db.commit()
    await db.refresh(driver)
    return DriverResponse.model_validate(driver)


@router.get("/jobs", response_model=list[BookingResponse])
async def list_jobs(
    limit: int = Query(default=20, ge=1, le=50),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
) -> list[BookingResponse]:
    if not driver.is_online:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Go online to see jobs",
        )

    await booking_service.expire_stale_bookings(db)

    result = await db.execute(
        select(Booking)
        .where(
            Booking.status == BookingStatus.pending,
            Booking.driver_id.is_(None),
            Booking.vehicle_type_code == driver.vehicle_type_code,
        )
        .order_by(Booking.created_at.desc())
        .limit(limit)
    )
    return [BookingResponse.model_validate(b) for b in result.scalars().all()]


@router.get("/bookings", response_model=list[BookingResponse])
async def list_my_bookings(
    limit: int = Query(default=20, ge=1, le=100),
    driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
) -> list[BookingResponse]:
    result = await db.execute(
        select(Booking)
        .where(Booking.driver_id == driver.id)
        .order_by(Booking.created_at.desc())
        .limit(limit)
    )
    return [BookingResponse.model_validate(b) for b in result.scalars().all()]
