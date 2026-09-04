from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RouteDistance(Base):
    """Cached road distance and duration for one origin/destination pair.

    Both values are cacheable under the Maps Platform Service Specific Terms,
    which permit temporarily caching "latitude (lat), longitude (lng),
    distance, duration, time, and estimated time of arrival values for up to
    30 consecutive calendar days, after which customers must delete the
    cached values".

    That is a WIDER exemption than the one governing place_coordinates: for
    Places, only the place id (indefinite) and lat/lng (30 days) may be kept,
    which is why that table has no address column. Here distance and duration
    are named explicitly.

    They are stored together but read apart — see route_cache for the two
    different freshness rules. Distance is stable for the full retention
    window; duration is traffic-dependent and goes stale in minutes.

    Deliberately not a TimestampMixin: an updated_at that moved on every
    refresh would make the 30-day retention clock unauditable. created_at is
    when these values came back from Google, which is the only thing the
    retention rule cares about.
    """

    __tablename__ = "route_distances"

    # "12.9352,77.6245" — coordinates rounded to 4 decimals (~11m) before
    # being formatted. Raw GPS gives 12.93521847, so two taps on the same spot
    # produce different keys and an exact match would never hit.
    origin_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    dest_key: Mapped[str] = mapped_column(String(32), primary_key=True)

    distance_m: Mapped[int] = mapped_column(nullable=False)
    duration_s: Mapped[int] = mapped_column(nullable=False)

    # Indexed because the retention sweep filters on it and runs on a hot
    # path. Same lesson as ix_bookings_pending_created_at.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
