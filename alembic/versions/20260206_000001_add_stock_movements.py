"""add_stock_movements

Revision ID: 20260206_000001
Revises: 20260204_000002
Create Date: 2026-02-06 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260206_000001'
down_revision = '20260204_000002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'stock_movements',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('lot_id', sa.BigInteger(), nullable=False),
        sa.Column('tipo', sa.String(length=10), nullable=False),
        sa.Column('cantidad', sa.Integer(), nullable=False),
        sa.Column('referencia', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint("tipo IN ('ENTRADA','SALIDA')", name='ck_stock_movement_tipo'),
        sa.ForeignKeyConstraint(['lot_id'], ['donation_lots.id'], ondelete='CASCADE'),
    )


def downgrade() -> None:
    op.drop_table('stock_movements')
