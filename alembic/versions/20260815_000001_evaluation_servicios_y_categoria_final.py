"""social_evaluations: servicios del hogar (agua/luz/gas/internet) + categoria_final

- tiene_agua/tiene_luz/tiene_gas_domiciliario/tiene_internet: indicador
  cualitativo de qué servicios tiene el hogar (no afecta el cálculo de CFNR).
- categoria_final: categoría que el entrevistador elige explícitamente al
  aprobar, pudiendo confirmar o corregir la sugerencia automática
  (categoria_asignada). Es la que queda vigente para el beneficiario.

Revision ID: 20260815_000001
Revises: 20260814_000004
Create Date: 2026-08-15

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260815_000001"
down_revision = "20260814_000004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "social_evaluations",
        sa.Column("tiene_agua", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("tiene_luz", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("tiene_gas_domiciliario", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("tiene_internet", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("categoria_final", sa.String(10), nullable=True),
    )


def downgrade():
    op.drop_column("social_evaluations", "categoria_final")
    op.drop_column("social_evaluations", "tiene_internet")
    op.drop_column("social_evaluations", "tiene_gas_domiciliario")
    op.drop_column("social_evaluations", "tiene_luz")
    op.drop_column("social_evaluations", "tiene_agua")
