import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.driver import Driver


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

    # The real fix for double-accept (spec 008 follow-up): a driver can only
    # have one row in driver_assigned/picked_up at a time. This is the
    # authoritative check — a prior SELECT-then-check has the exact same race
    # the original claim_booking spec was written to close. claim_booking
    # does a cheap pre-check for a friendly message, but this index is what
    # actually prevents it under concurrent accepts.
    __table_args__ = (
        Index(
            "one_active_booking_per_driver",
            "driver_id",
            unique=True,
            postgresql_where=text("status IN ('driver_assigned', 'picked_up')"),
        ),
        # Supports expire_stale_bookings, whose predicate is
        # (status = 'pending' AND created_at < cutoff).
        #
        # ix_bookings_status alone already kept this off a seq scan, but it
        # can only satisfy the status half: the plan was a bitmap scan over
        # every pending row followed by a Filter that discarded them all.
        # Measured on 200k rows with 5k pending and none expirable — the
        # steady state, since the sweep normally matches nothing — that read
        # 5006 buffers to update zero rows, and the cost grows with the
        # number of pending bookings. With created_at in the index the
        # predicate becomes an Index Cond and the heap is never touched:
        # 2 buffers, 4.7ms -> 0.055ms.
        #
        # Partial rather than a composite on (status, created_at): pending is
        # a small slice of a bookings table, so the index stays proportional
        # to live work instead of to history. 104 kB versus 5176 kB for
        # ix_bookings_status at that volume.
        Index(
            "ix_bookings_pending_created_at",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

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

    # lazy="raise" is deliberate, and it is the whole reason this relationship
    # is safe to add. On an async session, touching an unloaded relationship
    # cannot emit its SELECT — there is no await to hang it on — so it fails
    # with MissingGreenlet from deep inside attribute access, usually in a
    # response serialiser, where the traceback says nothing about the missing
    # eager load. "raise" turns that into an explicit, immediate error naming
    # this attribute, at the line that forgot to load it.
    #
    # Every read path that needs it must therefore ask for it:
    # selectinload(Booking.driver). On the list endpoint that is also what
    # keeps it to one extra query instead of one per booking.
    #
    # No reverse Driver.bookings: nothing traverses that direction, and each
    # lazy="raise" relationship is one more thing that can fail at runtime.
    driver: Mapped["Driver | None"] = relationship(lazy="raise")

    vehicle_type_code: Mapped[str] = mapped_column(
        ForeignKey("vehicle_types.code"), nullable=False
    )

    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status"),
        default=BookingStatus.pending,
        server_default=BookingStatus.pending.value,
        nullable=False,
        index=True,
    )

    # --- Locations -------------------------------------------------------
    # Float, not Numeric: coordinates don't need exact decimal arithmetic,
    # and float64 carries far more precision than 6 decimal places needs.
    pickup_address: Mapped[str] = mapped_column(String(255), nullable=False)
    pickup_lat: Mapped[float] = mapped_column(Float, nullable=False)
    pickup_lng: Mapped[float] = mapped_column(Float, nullable=False)

    drop_address: Mapped[str] = mapped_column(String(255), nullable=False)
    drop_lat: Mapped[float] = mapped_column(Float, nullable=False)
    drop_lng: Mapped[float] = mapped_column(Float, nullable=False)

    # Google place ids for whichever end came from address search rather than
    # a dropped pin. Nothing reads them yet.
    #
    # Captured now because they cannot be captured later: a place id is
    # stable and re-resolvable, where the free-text address beside it is
    # neither, and there is no way to back-fill an id for a booking that has
    # already happened. Cheap insurance against needing to re-derive "which
    # building was this actually" for a dispute or a delivery-density map.
    #
    # Also the one piece of Google content the Maps Platform terms allow us
    # to store indefinitely — everything else is capped at 30 days.
    pickup_place_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    drop_place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

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
        Numeric(4, 1, asdecimal=False), nullable=False
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
        server_default=PaymentMethod.cash.value,
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
