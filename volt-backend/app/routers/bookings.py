from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.driver_auth import get_current_driver
from app.models.driver import Driver
from app.models.user import User
from app.schemas.booking import (
    BookingCreate,
    BookingResponse,
    CancelRequest,
    EstimateRequest,
    EstimateResponse,
)
from app.services import booking as booking_service
from app.services.booking_lifecycle import (
    BookingAlreadyClaimed,
    BookingExpired,
    BookingNotFound,
    DriverHasActiveBooking,
    DriverOffline,
    IllegalTransition,
    VehicleTypeMismatch,
)
from app.services.fare import VehicleCapacityExceeded, VehicleTypeNotFound, estimate_all

router = APIRouter(prefix="/api/v1/bookings", tags=["bookings"])


@router.post("/estimate", response_model=EstimateResponse)
async def estimate_fare(
    payload: EstimateRequest,
    db: AsyncSession = Depends(get_db),
) -> EstimateResponse:
    distance_m, eta, options = await estimate_all(
        db,
        payload.pickup.lat,
        payload.pickup.lng,
        payload.drop.lat,
        payload.drop.lng,
        payload.approx_weight_kg,
    )
    return EstimateResponse(
        distance_m=distance_m, eta_minutes=eta, options=options
    )


@router.post(
    "",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_booking(
    payload: BookingCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BookingResponse:
    try:
        created = await booking_service.create_booking(db, payload, user)
    except VehicleTypeNotFound:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown vehicle type: {payload.vehicle_type_code}",
        )
    except VehicleCapacityExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    return BookingResponse.model_validate(created)


@router.get("", response_model=list[BookingResponse])
async def list_bookings(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[BookingResponse]:
    await booking_service.expire_stale_bookings(db)
    bookings = await booking_service.list_bookings_for_user(db, user.id, limit)
    return [BookingResponse.model_validate(b) for b in bookings]


@router.get("/{public_code}", response_model=BookingResponse)
async def get_booking(
    public_code: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BookingResponse:
    await booking_service.expire_stale_bookings(db)
    found = await booking_service.get_booking_by_code(db, public_code)
    if found is None or found.customer_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )
    return BookingResponse.model_validate(found)


@router.post("/{public_code}/accept", response_model=BookingResponse)
async def accept_booking(
    public_code: str,
    db: AsyncSession = Depends(get_db),
    driver: Driver = Depends(get_current_driver),
) -> BookingResponse:
    try:
        claimed = await booking_service.claim_booking(db, public_code, driver)
    except DriverOffline:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Go online to accept jobs",
        )
    except BookingNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )
    except VehicleTypeMismatch as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    except BookingExpired as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except BookingAlreadyClaimed as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except DriverHasActiveBooking as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return BookingResponse.model_validate(claimed)


@router.post("/{public_code}/pickup", response_model=BookingResponse)
async def pickup_booking(
    public_code: str,
    db: AsyncSession = Depends(get_db),
    driver: Driver = Depends(get_current_driver),
) -> BookingResponse:
    try:
        updated = await booking_service.mark_picked_up(db, public_code, driver)
    except BookingNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )
    except IllegalTransition as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return BookingResponse.model_validate(updated)


@router.post("/{public_code}/deliver", response_model=BookingResponse)
async def deliver_booking(
    public_code: str,
    db: AsyncSession = Depends(get_db),
    driver: Driver = Depends(get_current_driver),
) -> BookingResponse:
    try:
        updated = await booking_service.mark_delivered(db, public_code, driver)
    except BookingNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )
    except IllegalTransition as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return BookingResponse.model_validate(updated)


@router.post("/{public_code}/cancel", response_model=BookingResponse)
async def cancel_booking(
    public_code: str,
    payload: CancelRequest = CancelRequest(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BookingResponse:
    try:
        cancelled = await booking_service.cancel_booking(
            db, public_code, user, payload.cancellation_reason
        )
    except BookingNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )
    except IllegalTransition:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This booking can no longer be cancelled — it's already "
            "been picked up, delivered, or cancelled",
        )
    return BookingResponse.model_validate(cancelled)
