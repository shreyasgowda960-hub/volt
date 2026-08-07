"""seed vehicle types

Revision ID: e4f7afc44bc2
Revises: cf05ce9850a0
Create Date: 2026-08-07 13:59:19.057704

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4f7afc44bc2'
down_revision: Union[str, Sequence[str], None] = 'cf05ce9850a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


vehicle_types_table = sa.table(
    "vehicle_types",
    sa.column("code", sa.String),
    sa.column("label", sa.String),
    sa.column("base_fare_paise", sa.Integer),
    sa.column("included_km", sa.Numeric),
    sa.column("per_km_paise", sa.Integer),
    sa.column("min_fare_paise", sa.Integer),
    sa.column("capacity_kg", sa.Integer),
    sa.column("is_active", sa.Boolean),
    sa.column("sort_order", sa.Integer),
)

SEED_CODES = ["bike", "three_wheeler", "mini_truck"]


def upgrade() -> None:
    """Upgrade schema."""
    op.bulk_insert(
        vehicle_types_table,
        [
            {
                "code": "bike",
                "label": "Bike",
                "base_fare_paise": 3000,
                "included_km": 2.0,
                "per_km_paise": 800,
                "min_fare_paise": 4000,
                "capacity_kg": 20,
                "is_active": True,
                "sort_order": 1,
            },
            {
                "code": "three_wheeler",
                "label": "3-Wheeler",
                "base_fare_paise": 6000,
                "included_km": 3.0,
                "per_km_paise": 1300,
                "min_fare_paise": 8000,
                "capacity_kg": 500,
                "is_active": True,
                "sort_order": 2,
            },
            {
                "code": "mini_truck",
                "label": "Mini-Truck",
                "base_fare_paise": 12000,
                "included_km": 3.0,
                "per_km_paise": 2000,
                "min_fare_paise": 15000,
                "capacity_kg": 1250,
                "is_active": True,
                "sort_order": 3,
            },
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        vehicle_types_table.delete().where(
            vehicle_types_table.c.code.in_(SEED_CODES)
        )
    )
