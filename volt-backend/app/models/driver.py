import enum

from sqlalchemy import Enum, false, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class VerificationStatus(str, enum.Enum):
    """Where a driver is in document review.

    Unlike the booking lifecycle this one LOOPS: rejected goes back to
    submitted on resubmission. That is deliberate — a blurry photo is not a
    terminal judgement on a person, and a state machine that cannot loop
    would force a new driver record to fix one bad upload.

    `pending` means nothing uploaded yet, which is also where a brand-new
    driver starts. `submitted` requires BOTH documents present, so a driver
    who has uploaded only a licence is still `pending` — otherwise a
    half-finished driver appears in the reviewer's queue.
    """

    pending = "pending"
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"


class Driver(Base, TimestampMixin):
    """Minimal driver record. Phase 2 (driver app) extends this with
    onboarding, documents, and payout details."""

    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)

    phone: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Nullable: existing rows predate driver auth (spec 008). New rows get
    # this set at registration, same as User.firebase_uid.
    firebase_uid: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True, nullable=True
    )

    # e.g. 'KA 05 AB 1234'
    vehicle_number: Mapped[str] = mapped_column(String(20), nullable=False)

    vehicle_type_code: Mapped[str] = mapped_column(
        ForeignKey("vehicle_types.code"), nullable=False, index=True
    )

    is_online: Mapped[bool] = mapped_column(
        default=False, server_default=false(), nullable=False
    )

    # DERIVED from verification_status, not set independently (spec 017).
    # Before 017 this was hardcoded True at registration; now it is true only
    # when verification_status == approved.
    #
    # Kept as a separate column rather than replaced, because it is what
    # get_current_driver checks — so the auth gate keeps exactly the shape it
    # has always had and no auth code moved for this spec. The two must never
    # disagree: only the approve/reject endpoints write either of them.
    is_verified: Mapped[bool] = mapped_column(
        default=False, server_default=false(), nullable=False
    )

    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, name="verification_status"),
        nullable=False,
        default=VerificationStatus.pending,
        server_default=VerificationStatus.pending.value,
    )

    rating: Mapped[float | None] = mapped_column(
        Numeric(2, 1, asdecimal=False), nullable=True
    )
