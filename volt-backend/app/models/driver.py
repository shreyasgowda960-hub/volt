from sqlalchemy import false, ForeignKey, Numeric, String
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
    is_verified: Mapped[bool] = mapped_column(
        default=False, server_default=false(), nullable=False
    )

    rating: Mapped[float | None] = mapped_column(
        Numeric(2, 1, asdecimal=False), nullable=True
    )
