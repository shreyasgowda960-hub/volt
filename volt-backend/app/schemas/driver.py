from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.driver import VerificationStatus


class DriverRegister(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    vehicle_number: str = Field(min_length=1, max_length=20)
    vehicle_type_code: str


class DriverResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    name: str
    vehicle_number: str
    vehicle_type_code: str
    is_online: bool
    is_verified: bool
    # Derived from verification_status as of spec 017 — the two must never
    # disagree. Both are exposed because the driver app routes on the status
    # (which of four screens to show) while the backend gates on the bool.
    verification_status: VerificationStatus
    rating: float | None
    created_at: datetime


class AvailabilityUpdate(BaseModel):
    is_online: bool
