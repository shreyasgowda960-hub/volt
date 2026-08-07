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
