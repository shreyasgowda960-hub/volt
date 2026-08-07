"""add server_default to boolean and enum columns

Revision ID: 70b5d919a083
Revises: e4f7afc44bc2
Create Date: 2026-08-07 14:05:04.013548

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '70b5d919a083'
down_revision: Union[str, Sequence[str], None] = 'e4f7afc44bc2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Alembic's autogenerate doesn't compare server_default by default
    # (compare_server_default is off in env.py), so these are hand-written.
    op.alter_column("vehicle_types", "is_active", server_default=sa.true())
    op.alter_column("users", "is_active", server_default=sa.true())
    op.alter_column("drivers", "is_online", server_default=sa.false())
    op.alter_column("drivers", "is_verified", server_default=sa.false())
    op.alter_column("bookings", "status", server_default="pending")
    op.alter_column("bookings", "payment_method", server_default="cash")


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("bookings", "payment_method", server_default=None)
    op.alter_column("bookings", "status", server_default=None)
    op.alter_column("drivers", "is_verified", server_default=None)
    op.alter_column("drivers", "is_online", server_default=None)
    op.alter_column("users", "is_active", server_default=None)
    op.alter_column("vehicle_types", "is_active", server_default=None)
