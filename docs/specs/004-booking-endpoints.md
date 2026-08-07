# Spec 004 — Booking endpoints (server-side fare)

Build mode. Implement exactly as written.

**Precondition:** spec 003 applied. `\dt` shows `users`, `drivers`,
`vehicle_types`, `bookings`, `alembic_version`, and `vehicle_types` has three
rows. If not, stop.

## Guardrails

- **Do NOT add authentication in this spec.** It is spec 005. See the security
  note below — these endpoints are deliberately, temporarily unsafe.
- **Do NOT touch `customer_app/`.** Wiring the app to the API is spec 006.
- **Do NOT add dependencies.**
- **Do NOT deploy this.** Local only until spec 005 lands.
- Money is integer paise everywhere. No floats touch a fare.

## SECURITY — read this and keep it in mind while implementing

`POST /api/v1/bookings` accepts `customer_phone` in the request body and
trusts it. That means anyone who can reach this API can create a booking as
any customer.

This is a knowing, temporary trade so the app can be wired up before Firebase
lands. It is fixed in spec 005, where the customer is taken from a verified
Firebase token and the body field is deleted.

Consequences while it stands:

- Do not expose this server to the internet.
- Do not deploy to Render/Railway.
- Local WiFi only.

Add `# SECURITY: spec 005 replaces this with token-derived identity` at every
place the body-supplied phone is trusted, so the holes are greppable.

## What gets built

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/bookings/estimate` | Fares for all vehicle types, no booking created |
| POST | `/api/v1/bookings` | Create a booking, snapshotting the quote |
| GET | `/api/v1/bookings/{public_code}` | Read one booking |

## Step 1 — New file: `volt-backend/app/utils/codes.py`

```python
import secrets
import string

# No 0/O/1/I/L — these get misread when a customer reads a code to support.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_public_code(length: int = 8) -> str:
    """Human-readable booking reference, e.g. 'VLT7QK2M4X'.

    Random rather than sequential: a sequential public id lets anyone count
    daily order volume and probe other customers' bookings by incrementing.
    """
    body = "".join(secrets.choice(_ALPHABET) for _ in range(length))
    return f"VLT{body}"
```

## Step 2 — New file: `volt-backend/app/utils/distance.py`

```python
from math import atan2, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000

# Straight-line distance under-reports real road distance. 1.4 is a placeholder
# until Google Distance Matrix arrives in phase 3.
ROAD_FACTOR = 1.4

AVG_SPEED_KMH = 20.0


def road_distance_m(
    lat1: float, lng1: float, lat2: float, lng2: float
) -> int:
    """Great-circle distance times a road-winding factor, in metres."""
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2) ** 2
    )
    straight_m = EARTH_RADIUS_M * 2 * atan2(sqrt(a), sqrt(1 - a))
    return round(straight_m * ROAD_FACTOR)


def eta_minutes(distance_m: int) -> int:
    """Rough ETA from average city speed. Replaced by Maps in phase 3."""
    hours = (distance_m / 1000) / AVG_SPEED_KMH
    return max(1, round(hours * 60))
```

## Step 3 — New file: `volt-backend/app/schemas/booking.py`

```python
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
    # SECURITY: spec 005 removes this and derives the customer from the
    # verified Firebase token instead.
    customer_phone: str = Field(pattern=r"^\+91[6-9]\d{9}$")

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
```

Note what Pydantic is doing: `pattern` rejects a malformed phone, `ge`/`le`
reject impossible coordinates, `gt=0` rejects zero-weight goods. All before a
single line of your code runs. Invalid input never reaches the service layer.

## Step 4 — New file: `volt-backend/app/services/fare.py`

```python
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_type import VehicleType
from app.schemas.booking import FareOption
from app.utils.distance import eta_minutes, road_distance_m


class VehicleTypeNotFound(Exception):
    pass


def _fare_paise(vehicle: VehicleType, distance_m: int) -> int:
    """base + (billable km x per-km rate), floored at the minimum fare.

    Decimal, not float: included_km comes out of Postgres as Decimal, and
    mixing it with float silently reintroduces the rounding errors that
    integer paise exist to avoid.
    """
    distance_km = Decimal(distance_m) / Decimal(1000)
    billable_km = max(Decimal(0), distance_km - Decimal(vehicle.included_km))
    raw = Decimal(vehicle.base_fare_paise) + billable_km * Decimal(
        vehicle.per_km_paise
    )
    return max(int(raw.to_integral_value()), vehicle.min_fare_paise)


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


async def estimate_all(
    db: AsyncSession,
    pickup_lat: float,
    pickup_lng: float,
    drop_lat: float,
    drop_lng: float,
) -> tuple[int, int, list[FareOption]]:
    """Returns (distance_m, eta_minutes, options)."""
    distance_m = road_distance_m(pickup_lat, pickup_lng, drop_lat, drop_lng)
    eta = eta_minutes(distance_m)

    options = [
        FareOption(
            vehicle_type_code=v.code,
            label=v.label,
            capacity_kg=v.capacity_kg,
            fare_paise=_fare_paise(v, distance_m),
            distance_m=distance_m,
            eta_minutes=eta,
        )
        for v in await load_active_vehicle_types(db)
    ]
    return distance_m, eta, options
```

This module is the whole point of the backend. The fare is now computed on a
machine the customer cannot modify. The client-side version in
`customer_app/lib/features/booking/data/fare_estimator.dart` becomes a UX
nicety only — it is never authoritative.

## Step 5 — New file: `volt-backend/app/services/booking.py`

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking, BookingStatus
from app.models.user import User
from app.schemas.booking import BookingCreate
from app.services.fare import _fare_paise, load_vehicle_type
from app.utils.codes import generate_public_code
from app.utils.distance import eta_minutes, road_distance_m


async def get_or_create_user(db: AsyncSession, phone: str) -> User:
    """SECURITY: spec 005 replaces this with a lookup by verified Firebase uid.
    Trusting a phone number from the request body is temporary."""
    result = await db.execute(select(User).where(User.phone == phone))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(phone=phone)
        db.add(user)
        await db.flush()
    return user


async def _unique_public_code(db: AsyncSession) -> str:
    for _ in range(5):
        code = generate_public_code()
        existing = await db.execute(
            select(Booking.id).where(Booking.public_code == code)
        )
        if existing.scalar_one_or_none() is None:
            return code
    raise RuntimeError("could not generate a unique booking code")


async def create_booking(db: AsyncSession, payload: BookingCreate) -> Booking:
    vehicle = await load_vehicle_type(db, payload.vehicle_type_code)
    user = await get_or_create_user(db, payload.customer_phone)

    distance_m = road_distance_m(
        payload.pickup.lat,
        payload.pickup.lng,
        payload.drop.lat,
        payload.drop.lng,
    )

    booking = Booking(
        public_code=await _unique_public_code(db),
        customer_id=user.id,
        vehicle_type_code=vehicle.code,
        status=BookingStatus.pending,
        pickup_address=payload.pickup.address,
        pickup_lat=payload.pickup.lat,
        pickup_lng=payload.pickup.lng,
        drop_address=payload.drop.address,
        drop_lat=payload.drop.lat,
        drop_lng=payload.drop.lng,
        goods_description=payload.goods_description,
        approx_weight_kg=payload.approx_weight_kg,
        quoted_fare_paise=_fare_paise(vehicle, distance_m),
        quoted_distance_m=distance_m,
        quoted_eta_minutes=eta_minutes(distance_m),
        # Rate snapshot: changing vehicle_types next month must never rewrite
        # what this booking was quoted.
        quoted_base_fare_paise=vehicle.base_fare_paise,
        quoted_included_km=vehicle.included_km,
        quoted_per_km_paise=vehicle.per_km_paise,
        quoted_min_fare_paise=vehicle.min_fare_paise,
        payment_method=payload.payment_method,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    return booking


async def get_booking_by_code(
    db: AsyncSession, public_code: str
) -> Booking | None:
    result = await db.execute(
        select(Booking).where(Booking.public_code == public_code)
    )
    return result.scalar_one_or_none()
```

Note the fare is recomputed server-side at creation. The client sends
locations and a vehicle choice, never a price. A client-supplied price would
be trivially forged.

## Step 6 — New file: `volt-backend/app/routers/bookings.py`

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.booking import (
    BookingCreate,
    BookingResponse,
    EstimateRequest,
    EstimateResponse,
)
from app.services import booking as booking_service
from app.services.fare import VehicleTypeNotFound, estimate_all

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
) -> BookingResponse:
    # SECURITY: customer identity comes from the request body until spec 005.
    try:
        created = await booking_service.create_booking(db, payload)
    except VehicleTypeNotFound:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown vehicle type: {payload.vehicle_type_code}",
        )
    return BookingResponse.model_validate(created)


@router.get("/{public_code}", response_model=BookingResponse)
async def get_booking(
    public_code: str,
    db: AsyncSession = Depends(get_db),
) -> BookingResponse:
    # SECURITY: no ownership check. Spec 005 verifies the caller owns this
    # booking. Until then anyone with a code can read any booking.
    found = await booking_service.get_booking_by_code(db, public_code)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )
    return BookingResponse.model_validate(found)
```

Notice the router contains no business logic — it reads the request, calls a
service, shapes a response. That is the whole job of the HTTP layer.

## Step 7 — Edit `volt-backend/app/main.py`

Add the router import and registration. Keep the existing health endpoint
unchanged:

```python
from app.routers import bookings

app.include_router(bookings.router)
```

## Step 8 — Verify manually

Restart the server:

```powershell
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` and use the interactive UI — it is faster
than curl on Windows and shows the exact request shape.

**Estimate** — POST `/api/v1/bookings/estimate`:

```json
{
  "pickup": {"address": "Koramangala", "lat": 12.9352, "lng": 77.6245},
  "drop": {"address": "Whitefield", "lat": 12.9698, "lng": 77.7500}
}
```

Expect three options. Cross-check one against the Flutter app's number for the
same pair — they should match within a rupee or two. Report the numbers.

**Create** — POST `/api/v1/bookings`:

```json
{
  "customer_phone": "+919876543210",
  "pickup": {"address": "Koramangala", "lat": 12.9352, "lng": 77.6245},
  "drop": {"address": "Whitefield", "lat": 12.9698, "lng": 77.7500},
  "vehicle_type_code": "bike",
  "goods_description": "Two cartons of books",
  "approx_weight_kg": 12.5,
  "payment_method": "cash"
}
```

Expect 201 and a `public_code`.

**Read** — GET `/api/v1/bookings/{that code}`. Expect the same booking.

**Then check the rows landed:**

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -U postgres -d volt_dev -c "SELECT public_code, status, quoted_fare_paise, quoted_distance_m FROM bookings;"
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -U postgres -d volt_dev -c "SELECT id, phone FROM users;"
```

**Error paths, confirm each:**

- Unknown `vehicle_type_code` → 422
- `customer_phone` of `"9876543210"` (no +91) → 422 from Pydantic
- `approx_weight_kg` of `0` → 422
- GET a nonexistent code → 404

## Step 9 — Update `CLAUDE.md`

Add to "Current state":

```
API: POST /api/v1/bookings/estimate, POST /api/v1/bookings,
GET /api/v1/bookings/{public_code}. Fare is computed server-side from the
vehicle_types table and snapshotted onto each booking.
NOT AUTHENTICATED — customer identity comes from the request body. Local use
only, do not deploy, until spec 005 adds Firebase token verification.
```

## Step 10 — Report and stop

1. Files created or edited
2. The three fare numbers from the estimate call, and whether they match the
   Flutter app for the same route
3. The `public_code` created, and the psql output showing the rows
4. Which error paths you confirmed
5. Any deviation, and why

Do not wire the Flutter app to this API — that is spec 006. Do not add auth —
that is spec 005. Stop here.
