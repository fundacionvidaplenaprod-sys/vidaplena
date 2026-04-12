"""add_payload_patient_status_events

Revision ID: 20260204_000002
Revises: 20260204_000001
Create Date: 2026-02-04 00:00:02.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '20260204_000002'
down_revision = '20260204_000001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'patient_status_events',
        sa.Column('payload', postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('patient_status_events', 'payload')
