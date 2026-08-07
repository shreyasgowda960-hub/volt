# Spec 003 — Database schema (users, drivers, vehicle_types, bookings)

Build mode. Implement exactly as written.

## Guardrails

- **Do NOT create routers, endpoints, or services in this spec.** Models and
  migrations only. Endpoints are spec 004.
- **Do NOT add dependencies.** Everything needed is already installed.
- **Do NOT touch `customer_app/`.**
- Money is **integer paise**, always. Every money column name ends `_paise`.
  Never `Float`, never `Numeric`, for money.
- If a design choice here looks wrong to you, **say so before implementing** —
  do not silently improve it.

## Decisions being implemented

| Decision | Value |
|---|---|
| Money | Integer paise, columns suffixed `_paise` |
| Cancellation | Free any time before pickup; no fee columns |
| Goods | Description + approximate weight, both required |
| Public IDs | Internal `BigInteger` PK + separate human-readable `public_code` |
| Fare rates | `vehicle_types` table, snapshotted onto each booking |
| Status | Derived from timestamps, plus an explicit enum column |
| Failure modes | `cancelled` and `expired` are distinct states |

## Step 1 — Alembic init

From `volt-backend/` with the venv active:

```powershell
alembic init -t async alembic
```

The `-t async` template matters — the default template generates sync
migrations that will fail against `asyncpg`.

## Step 2 — Edit `volt-backend/alembic.ini`

Find the `sqlalchemy.url` line and set it to empty:

```ini
sqlalchemy.url =
```

The URL comes from `.env` at runtime instead, so the database password never
enters a committed file.

## Step 3 — Edit `volt-backend/alembic/env.py`

Replace the whole file:

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.config import get_settings
from app.database import Base
from app.models import booking, driver, user, vehicle_type  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

The `from app.models import ...` line is what lets Alembic autogenerate see the
tables. A model not imported there is invisible to migrations — a silent and
very common failure.

## Step 4 — New file: `volt-backend/app/models/__init__.py`

```python
from app.models.booking import Booking, BookingStatus, CancelledBy, PaymentMethod
from app.models.driver import Driver
from app.models.user import User
from app.models.vehicle_type import VehicleType

__all__ = [
    "Booking",
    "BookingStatus",
    "CancelledBy",
    "Driver",
    "PaymentMethod",
    "User",
    "VehicleType",
]
```

## Step 5 — New file: `volt-backend/app/models/mixins.py`

```python
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Server-side timestamps. Uses the database clock, not the app server's,
    so records stay consistent across multiple app instances."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

## Step 6 — New file: `volt-backend/app/models/user.py`

```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    """A customer. Phone is the identity — VOLT is phone-first, there are no
    email/password accounts."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    # E.164, e.g. +919876543210. Unique because it IS the identity.
    phone: Mapped[str] = mapped_column(String(16), unique=True, index=True)

    # Null until real Firebase auth replaces FakeAuthRepository. Kept separate
    # from phone so a user can change number without losing their account.
    firebase_uid: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True, nullable=True
    )

    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
```

## Step 7 — New file: `volt-backend/app/models/vehicle_type.py`

```python
from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class VehicleType(Base, TimestampMixin):
    """Current fare rates. Lives in the database so pricing changes are an
    UPDATE rather than a deploy.

    These are the CURRENT rates only. Every booking snapshots the rates it was
    quoted at, so changing a row here never rewrites past bookings.
    """

    __tablename__ = "vehicle_types"

    # Natural key: 'bike', 'three_wheeler', 'mini_truck'. Stable and readable
    # in the API, unlike an auto-increment id.
    code: Mapped[str] = mapped_column(String(20), primary_key=True)

    label: Mapped[str] = mapped_column(String(50), nullable=False)

    base_fare_paise: Mapped[int] = mapped_column(nullable=False)
    included_km: Mapped[float] = mapped_column(Numeric(4, 1), nullable=False)
    per_km_paise: Mapped[int] = mapped_column(nullable=False)
    min_fare_paise: Mapped[int] = mapped_column(nullable=False)

    capacity_kg: Mapped[int] = mapped_column(nullable=False)

    # Retire a category by flipping this, never by deleting the row —
    # bookings reference the code.
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
```

## Step 8 — New file: `volt-backend/app/models/driver.py`

```python
from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class Driver(Base, TimestampMixin):
    """Minimal driver record. Phase 2 (driver app) extends this with
    onboarding, documents, and payout details."""

    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)

    phone: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # e.g. 'KA 05 AB 1234'
    vehicle_number: Mapped[str] = mapped_column(String(20), nullable=False)

    vehicle_type_code: Mapped[str] = mapped_column(
        ForeignKey("vehicle_types.code"), nullable=False, index=True
    )

    is_online: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(default=False, nullable=False)

    rating: Mapped[float | None] = mapped_column(Numeric(2, 1), nullable=True)
```

## Step 9 — New file: `volt-backend/app/models/booking.py`

```python
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class BookingStatus(str, enum.Enum):
    """`cancelled` and `expired` are deliberately distinct: one is a customer
    choice, the other is a supply failure. Collapsing them destroys the only
    metric that tells you whether you have enough drivers."""

    pending = "pending"
    driver_assigned = "driver_assigned"
    picked_up = "picked_up"
    delivered = "delivered"
    cancelled = "cancelled"
    expired = "expired"


class CancelledBy(str, enum.Enum):
    customer = "customer"
    driver = "driver"
    system = "system"


class PaymentMethod(str, enum.Enum):
    cash = "cash"
    online = "online"


class Booking(Base, TimestampMixin):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)

    # What the customer and support see, e.g. 'VLT7QK2M4X'. Never expose `id`:
    # sequential public ids let anyone count daily order volume and probe
    # other customers' bookings by incrementing a number.
    public_code: Mapped[str] = mapped_column(
        String(16), unique=True, index=True, nullable=False
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    # Null until a driver accepts.
    driver_id: Mapped[int | None] = mapped_column(
        ForeignKey("drivers.id"), nullable=True, index=True
    )

    vehicle_type_code: Mapped[str] = mapped_column(
        ForeignKey("vehicle_types.code"), nullable=False
    )

    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status"),
        default=BookingStatus.pending,
        nullable=False,
        index=True,
    )

    # --- Locations -------------------------------------------------------
    # Numeric, not Float: 6 decimal places is ~11cm precision, and exact
    # decimal storage means a round-trip never shifts a coordinate.
    pickup_address: Mapped[str] = mapped_column(String(255), nullable=False)
    pickup_lat: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    pickup_lng: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)

    drop_address: Mapped[str] = mapped_column(String(255), nullable=False)
    drop_lat: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    drop_lng: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)

    # --- Goods -----------------------------------------------------------
    goods_description: Mapped[str] = mapped_column(String(255), nullable=False)
    approx_weight_kg: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False
    )

    # --- Money: the quote ------------------------------------------------
    # IMMUTABLE once written. This is what the customer agreed to, and it is
    # the answer to "I was overcharged" three days later.
    quoted_fare_paise: Mapped[int] = mapped_column(nullable=False)
    quoted_distance_m: Mapped[int] = mapped_column(nullable=False)
    quoted_eta_minutes: Mapped[int] = mapped_column(nullable=False)

    # Rate snapshot. Without these, raising bike prices next month silently
    # rewrites the history of every past booking and your GST invoices stop
    # reconciling with what customers actually paid.
    quoted_base_fare_paise: Mapped[int] = mapped_column(nullable=False)
    quoted_included_km: Mapped[float] = mapped_column(
        Numeric(4, 1), nullable=False
    )
    quoted_per_km_paise: Mapped[int] = mapped_column(nullable=False)
    quoted_min_fare_paise: Mapped[int] = mapped_column(nullable=False)

    # --- Money: the settlement -------------------------------------------
    # Null until the trip ends. Differs from quoted when distance, waiting, or
    # a support adjustment changes things.
    final_fare_paise: Mapped[int | None] = mapped_column(nullable=True)
    final_distance_m: Mapped[int | None] = mapped_column(nullable=True)

    payment_method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, name="payment_method"),
        default=PaymentMethod.cash,
        nullable=False,
    )

    # --- Lifecycle timestamps --------------------------------------------
    # One per transition. NULL always means "has not happened", never "unknown".
    # Status is derivable from these, which makes an impossible state (e.g.
    # delivered with no picked_up_at) detectable.
    driver_assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    picked_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cancelled_by: Mapped[CancelledBy | None] = mapped_column(
        Enum(CancelledBy, name="cancelled_by"), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
```

## Step 10 — Generate and apply the migration

```powershell
alembic revision --autogenerate -m "create users, drivers, vehicle_types, bookings"
```

**Open the generated file under `alembic/versions/` and read it before
applying.** Autogenerate is good but not infallible; confirm it creates four
tables and three enum types, and that no table is missing.

```powershell
alembic upgrade head
```

Verify:

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -U postgres -d volt_dev -c "\dt"
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -U postgres -d volt_dev -c "\d bookings"
```

You should see `users`, `drivers`, `vehicle_types`, `bookings`, and
`alembic_version`.

## Step 11 — Seed the vehicle types

Create a **second** migration for the seed data, not a script. Seed data that
lives in a migration is version-controlled, runs identically on every machine,
and arrives automatically when a teammate runs `alembic upgrade head`.

```powershell
alembic revision -m "seed vehicle types"
```

In the generated file, fill in `upgrade()` and `downgrade()` using
`op.bulk_insert` against a lightweight table definition. Rates in paise, and
these must match `customer_app/lib/features/booking/domain/vehicle_type.dart`
exactly:

| code | label | base_fare_paise | included_km | per_km_paise | min_fare_paise | capacity_kg | sort_order |
|---|---|---|---|---|---|---|---|
| `bike` | Bike | 3000 | 2.0 | 800 | 4000 | 20 | 1 |
| `three_wheeler` | 3-Wheeler | 6000 | 3.0 | 1300 | 8000 | 500 | 2 |
| `mini_truck` | Mini-Truck | 12000 | 3.0 | 2000 | 15000 | 1250 | 3 |

`downgrade()` deletes those three rows by code.

Then:

```powershell
alembic upgrade head
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -U postgres -d volt_dev -c "SELECT * FROM vehicle_types;"
```

## Step 12 — Confirm the app still starts

```powershell
uvicorn app.main:app --reload
```

`http://127.0.0.1:8000/api/v1/health` must still return ok. Importing models
should not break startup.

## Step 13 — Update `CLAUDE.md`

Add to "Current state":

```
Schema: users, drivers, vehicle_types, bookings. Alembic configured (async
template), 2 migrations applied. Money is integer paise everywhere. Bookings
snapshot their quoted rates so pricing changes never rewrite past bookings.
Status derived from per-transition timestamps; cancelled and expired distinct.
```

## Step 14 — Report and stop

1. Every file created or edited
2. Output of `\dt` and `SELECT * FROM vehicle_types;`
3. Anything in the autogenerated migration that looked wrong
4. Any deviation from this spec, and why

Do not write routers, endpoints, Pydantic schemas, or services. That is spec
004. Stop here.
