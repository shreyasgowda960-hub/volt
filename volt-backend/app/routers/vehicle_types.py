from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.vehicle_type import VehicleTypeResponse
from app.services.fare import load_active_vehicle_types

router = APIRouter(prefix="/api/v1/vehicle-types", tags=["vehicle-types"])


@router.get("", response_model=list[VehicleTypeResponse])
async def list_vehicle_types(
    db: AsyncSession = Depends(get_db),
) -> list[VehicleTypeResponse]:
    """Public — price-list data customers already see via fare estimates.
    Used by the driver app's registration screen so vehicle categories live
    in one place (the DB) instead of being duplicated in Dart."""
    vehicles = await load_active_vehicle_types(db)
    return [VehicleTypeResponse.model_validate(v) for v in vehicles]
