"""driver document verification

Revision ID: f6afa0f7088f
Revises: afbcf9152650
Create Date: 2026-09-06 18:28:44.417003

Hand-corrected after autogenerate, in three places. The generated version
would have failed on upgrade AND on re-upgrade, in the way CLAUDE.md warns
about:

1. `op.add_column` with `sa.Enum` does NOT emit CREATE TYPE on PostgreSQL, so
   verification_status has to be created explicitly first and the column then
   declared with create_type=False.
2. `create_table` DOES create its enum types, but `drop_table` does not drop
   them — so downgrade-then-upgrade died on "type already exists". The
   downgrade drops all three types.
3. The grandfathering UPDATE below, which autogenerate cannot know about.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f6afa0f7088f'
down_revision: Union[str, Sequence[str], None] = 'afbcf9152650'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'driver_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('driver_id', sa.Integer(), nullable=False),
        sa.Column(
            'document_type',
            sa.Enum('driving_licence', 'vehicle_rc', name='document_type'),
            nullable=False,
        ),
        sa.Column('storage_path', sa.String(length=512), nullable=False),
        sa.Column('document_number', sa.String(length=64), nullable=True),
        sa.Column(
            'status',
            sa.Enum('submitted', 'approved', 'rejected', name='document_status'),
            nullable=False,
        ),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_by', sa.String(length=120), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_driver_documents_driver_id'),
        'driver_documents',
        ['driver_id'],
        unique=False,
    )
    # Partial: rejected rows are excluded so a driver can resubmit while the
    # rejected original stays on the record.
    op.create_index(
        'one_live_document_per_driver_type',
        'driver_documents',
        ['driver_id', 'document_type'],
        unique=True,
        postgresql_where=sa.text("status <> 'rejected'"),
    )

    # CREATE TYPE explicitly — add_column will not do it. checkfirst so a
    # partially-applied run can be retried.
    verification_status = sa.Enum(
        'pending', 'submitted', 'approved', 'rejected', name='verification_status'
    )
    verification_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'drivers',
        sa.Column(
            'verification_status',
            postgresql.ENUM(
                'pending',
                'submitted',
                'approved',
                'rejected',
                name='verification_status',
                create_type=False,
            ),
            server_default='pending',
            nullable=False,
        ),
    )

    # --- ONE-TIME DATA MIGRATION FOR PRE-SPEC-017 ROWS ------------------
    # Every existing driver has is_verified=True from the old auto-approve at
    # registration. Left at the 'pending' default they would all be locked out
    # of get_current_driver the moment this deploys — including the owner's own
    # test driver, mid-demo.
    #
    # Grandfathering them to 'approved' is the honest reading: they WERE
    # approved, by a policy that trusted everyone. It does not retroactively
    # verify any documents, because there are none.
    #
    # MUST NOT BE REPEATED. This is correct exactly once, for rows that predate
    # this revision. A later migration running the same UPDATE would approve
    # every driver who had been deliberately rejected.
    op.execute(
        "UPDATE drivers SET verification_status = 'approved' WHERE is_verified = true"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('drivers', 'verification_status')
    op.drop_index(
        'one_live_document_per_driver_type',
        table_name='driver_documents',
        postgresql_where=sa.text("status <> 'rejected'"),
    )
    op.drop_index(
        op.f('ix_driver_documents_driver_id'), table_name='driver_documents'
    )
    op.drop_table('driver_documents')

    # All three types, dropped AFTER the things that use them. Neither
    # drop_column nor drop_table removes a type, so without this the next
    # upgrade fails with "type already exists" — which is how this was found.
    for name in ('verification_status', 'document_status', 'document_type'):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
