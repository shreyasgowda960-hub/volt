from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.booking import (
    BookingCreate,
    BookingResponse,
    EstimateRequest,
    EstimateResponse,
)
from app.services import booking as booking_service
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
    bookings = await booking_service.list_bookings_for_user(db, user.id, limit)
    return [BookingResponse.model_validate(b) for b in bookings]


@router.get("/{public_code}", response_model=BookingResponse)
async def get_booking(
    public_code: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BookingResponse:
    found = await booking_service.get_booking_by_code(db, public_code)
    if found is None or found.customer_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )
    return BookingResponse.model_validate(found)
