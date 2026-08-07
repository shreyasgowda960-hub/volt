from sqlalchemy import Numeric, String, true
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
    included_km: Mapped[float] = mapped_column(
        Numeric(4, 1, asdecimal=False), nullable=False
    )
    per_km_paise: Mapped[int] = mapped_column(nullable=False)
    min_fare_paise: Mapped[int] = mapped_column(nullable=False)

    capacity_kg: Mapped[int] = mapped_column(nullable=False)

    # Retire a category by flipping this, never by deleting the row —
    # bookings reference the code.
    is_active: Mapped[bool] = mapped_column(
        default=True, server_default=true(), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
