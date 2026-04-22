"""add imc column to patients

Revision ID: 871c945710ae
Revises: 2d83fa471857
Create Date: 2026-04-21 13:38:16.303599

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '871c945710ae'
down_revision = '2d83fa471857'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('patients', sa.Column('imc', sa.Numeric(precision=5, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column('patients', 'imc')