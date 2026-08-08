from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.booking import BookingStatus, PaymentMethod


class LocationIn(BaseModel):
    address: str = Field(min_length=1, max_length=255)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class EstimateRequest(BaseModel):
    pickup: LocationIn
    drop: LocationIn


class FareOption(BaseModel):
    vehicle_type_code: str
    label: str
    capacity_kg: int
    fare_paise: int
    distance_m: int
    eta_minutes: int


class EstimateResponse(BaseModel):
    distance_m: int
    eta_minutes: int
    options: list[FareOption]


class BookingCreate(BaseModel):
    pickup: LocationIn
    drop: LocationIn
    vehicle_type_code: str
    goods_description: str = Field(min_length=1, max_length=255)
    approx_weight_kg: float = Field(gt=0, le=2000)
    payment_method: PaymentMethod = PaymentMethod.cash


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_code: str
    status: BookingStatus
    vehicle_type_code: str

    pickup_address: str
    drop_address: str

    goods_description: str
    approx_weight_kg: float

    quoted_fare_paise: int
    quoted_distance_m: int
    quoted_eta_minutes: int
    final_fare_paise: int | None

    payment_method: PaymentMethod
    created_at: datetime


class ErrorResponse(BaseModel):
    """One consistent error shape across every endpoint."""

    detail: str
    code: str
