"""patient_status_events

Revision ID: 20260204_000001
Revises: ca352e2b0a60
Create Date: 2026-02-04 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260204_000001'
down_revision = 'ca352e2b0a60'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'patient_status_events',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('patient_id', sa.BigInteger(), sa.ForeignKey('patients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('old_state', sa.String(length=32), nullable=False),
        sa.Column('new_state', sa.String(length=32), nullable=False),
        sa.Column('observacion', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('patient_status_events')
