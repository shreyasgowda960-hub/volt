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

    rating: Mapped[float | None] = mapped_column(
        Numeric(2, 1, asdecimal=False), nullable=True
    )
