from datetime import datetime

from sqlalchemy import DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlaceCoordinate(Base):
    """Cached coordinates for a Google place id.

    Scope is set by the Maps Platform terms, not by what would be convenient.
    Of everything Google returns, exactly two things may be kept: a place id,
    indefinitely, and latitude/longitude, for up to 30 consecutive days after
    which they must be deleted. Addresses, display names and autocomplete
    predictions may not be cached at all — which is why there is no `address`
    column here, however obviously useful one would look.

    Deliberately NOT a TimestampMixin: `updated_at` would move on every
    refresh and make the 30-day clock unauditable. `cached_at` is the moment
    the coordinates arrived from Google, and it is the only thing the
    retention rule cares about.
    """

    __tablename__ = "place_coordinates"

    # Google's own id is the natural key — stable, unique, and the one field
    # we are allowed to keep forever.
    place_id: Mapped[str] = mapped_column(String(255), primary_key=True)

    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)

    # Indexed because the retention sweep filters on it, and that sweep runs
    # on a hot path. Same lesson as ix_bookings_pending_created_at.
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
