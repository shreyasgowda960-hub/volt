import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.driver_auth import get_current_driver
from app.models.driver import Driver
from app.models.user import User
from app.schemas.booking import (
    BookingCreate,
    BookingDetailResponse,
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
from app.services.service_area import OutsideServiceArea, check_within_service_area

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/bookings", tags=["bookings"])


@router.post("/estimate", response_model=EstimateResponse)
async def estimate_fare(
    payload: EstimateRequest,
    db: AsyncSession = Depends(get_db),
) -> EstimateResponse:
    # Checked in the route rather than in estimate_all, because unlike
    # create_booking there is no service function here that owns the request
    # as a whole — estimate_all takes loose coordinates and returns prices.
    try:
        check_within_service_area(payload.pickup.lat, payload.pickup.lng, "pickup")
        check_within_service_area(payload.drop.lat, payload.drop.lng, "drop")
    except OutsideServiceArea as e:
        logger.info("estimate refused: %s", e)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.user_message,
        )

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
    except OutsideServiceArea as e:
        logger.info("booking refused for %s: %s", user.id, e)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.user_message,
        )
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


# The two customer read endpoints below are the only routes returning
# BookingDetailResponse. The driver-facing ones (/drivers/jobs,
# /drivers/bookings, and accept/pickup/deliver) deliberately stay on the
# narrower BookingResponse — a driver has no business receiving the
# customer-facing view of a booking.
@router.get("", response_model=list[BookingDetailResponse])
async def list_bookings(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[BookingDetailResponse]:
    await booking_service.expire_stale_bookings(db)
    # list_bookings_for_user eager-loads the driver; without that,
    # serialising `driver` below raises on the lazy="raise" relationship.
    bookings = await booking_service.list_bookings_for_user(db, user.id, limit)
    return [BookingDetailResponse.model_validate(b) for b in bookings]


@router.get("/{public_code}", response_model=BookingDetailResponse)
async def get_booking(
    public_code: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BookingDetailResponse:
    await booking_service.expire_stale_bookings(db)
    found = await booking_service.get_booking_with_driver(db, public_code)
    if found is None or found.customer_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )
    return BookingDetailResponse.model_validate(found)


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
        # Technical detail to the log, plain language to the driver. The old
        # detail=str(e) put "Cannot move booking from BookingStatus.picked_up
        # to BookingStatus.picked_up" on a driver's screen.
        logger.info("pickup refused for %s: %s", public_code, e)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=e.user_message
        )
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
        logger.info("deliver refused for %s: %s", public_code, e)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=e.user_message
        )
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
    except IllegalTransition as e:
        # Was a hedge listing three possibilities ("picked up, delivered, or
        # cancelled") because the route could not tell which. user_message
        # knows the actual current status, so say that instead.
        logger.info("cancel refused for %s: %s", public_code, e)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=e.user_message
        )
    return BookingResponse.model_validate(cancelled)
