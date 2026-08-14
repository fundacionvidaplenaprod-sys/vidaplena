"""social_evaluations: switch to Capacidad Financiera Neta Residual (CFNR)

Adds monto_servicios_basicos, monto_transporte, monto_deuda_mensual
(costos declarados) y cfnr, costo_vida_estimado (resultados del nuevo
motor de categorización ALTA/MEDIA/BAJA).

Revision ID: 20260814_000001
Revises: 20260813_000001
Create Date: 2026-08-14

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260814_000001"
down_revision = "20260813_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "social_evaluations",
        sa.Column("monto_deuda_mensual", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("monto_servicios_basicos", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("monto_transporte", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("costo_vida_estimado", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("cfnr", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("social_evaluations", "cfnr")
    op.drop_column("social_evaluations", "costo_vida_estimado")
    op.drop_column("social_evaluations", "monto_transporte")
    op.drop_column("social_evaluations", "monto_servicios_basicos")
    op.drop_column("social_evaluations", "monto_deuda_mensual")
