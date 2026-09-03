"""add observaciones to departmental_insulin_deliveries

El responsable departamental necesita dejar observaciones libres sobre el
beneficiario al registrar una entrega (cambio de insulina solicitado,
impedimento por viaje, fallecimiento, sospecha de reventa/exceso de
insulina, etc.), visibles para el Coordinador Nacional y SUPER_ADMIN.

Revision ID: 20260904_000001
Revises: 20260903_000001
Create Date: 2026-09-04

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260904_000001"
down_revision = "20260903_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "departmental_insulin_deliveries",
        sa.Column("observaciones", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("departmental_insulin_deliveries", "observaciones")
