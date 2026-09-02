from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.booking import BookingStatus, CancelledBy, PaymentMethod
from app.services.booking_lifecycle import TERMINAL_STATUSES


class LocationIn(BaseModel):
    address: str = Field(min_length=1, max_length=255)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class EstimateRequest(BaseModel):
    pickup: LocationIn
    drop: LocationIn
    approx_weight_kg: float | None = Field(default=None, gt=0, le=2000)


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


class AssignedDriverResponse(BaseModel):
    """Driver details shown to the CUSTOMER of a booking.

    Includes phone so the customer can call about access, gates, floors.
    Deliberately one-directional: the driver does not receive customer
    contact details. Masked two-way calling is the eventual fix.

    `phone` is nullable and is stripped once the booking reaches a terminal
    status — see BookingDetailResponse._hide_driver_phone_once_terminal.
    """

    model_config = ConfigDict(from_attributes=True)

    name: str
    phone: str | None
    vehicle_number: str
    vehicle_type_code: str
    rating: float | None


class BookingDetailResponse(BookingResponse):
    """BookingResponse plus the assigned driver. Customer endpoints only.

    The lifecycle timestamps live here rather than on BookingResponse for the
    same reason `driver` does: they are what the customer's tracking timeline
    renders, and the driver-facing endpoints have no use for them. Widening
    the shared parent would hand every caller fields it never asked for.
    """

    driver: AssignedDriverResponse | None

    driver_assigned_at: datetime | None
    picked_up_at: datetime | None
    delivered_at: datetime | None
    cancelled_at: datetime | None
    expired_at: datetime | None

    cancelled_by: CancelledBy | None
    cancellation_reason: str | None

    @model_validator(mode="after")
    def _hide_driver_phone_once_terminal(self) -> "BookingDetailResponse":
        """A driver's mobile number is operational data, not history.

        The customer needs it while the trip is live — to talk about gates,
        floors, a locked gate, where exactly to park. Once the booking is
        delivered, cancelled or expired that need is gone, but the endpoint
        would keep returning the number for the rest of the booking's life.
        Every customer would slowly accumulate a permanent, private list of
        driver mobile numbers with no purpose behind it.

        Cancelled is the case that matters most, and it cuts the same way:
        the customer still sees who cancelled on them (name, vehicle number)
        because that is legitimately their business, but not the number. An
        aggrieved customer phoning a driver directly about a cancellation is
        exactly the channel not to open; disputes go through support.

        Enforced here, on the schema, rather than at each call site — a rule
        about what may leave the server should not depend on every future
        route remembering it.
        """
        if self.driver is not None and self.status in TERMINAL_STATUSES:
            self.driver.phone = None
        return self


class CancelRequest(BaseModel):
    cancellation_reason: str | None = Field(default=None, max_length=255)


class ErrorResponse(BaseModel):
    """One consistent error shape across every endpoint."""

    detail: str
    code: str
