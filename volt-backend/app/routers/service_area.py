from fastapi import APIRouter

from app.config import get_settings
from app.schemas.service_area import ServiceAreaResponse

router = APIRouter(prefix="/api/v1", tags=["service-area"])


@router.get("/service-area", response_model=ServiceAreaResponse)
async def get_service_area() -> ServiceAreaResponse:
    """Public, like POST /bookings/estimate.

    Where a logistics company operates is not a secret — it is on the
    marketing site — and the apps need it before anyone has signed in, to
    centre the map on the first screen.
    """
    settings = get_settings()
    return ServiceAreaResponse(
        center_lat=settings.service_center_lat,
        center_lng=settings.service_center_lng,
        radius_km=settings.service_radius_km,
    )
