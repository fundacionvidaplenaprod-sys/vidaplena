"""social_evaluations: ingreso_otros_familiares + montos itemizados por servicio

- ingreso_otros_familiares: ingreso de otros miembros del hogar (aparte de
  titular/cónyuge), suma al ingreso total del CFNR.
- monto_agua/monto_luz/monto_gas_domiciliario/monto_internet: reemplazan al
  monto único `monto_servicios_basicos`. Cada uno se declara junto a su
  respectivo `tiene_*` y solo entra al CFNR si ese `tiene_*` es True.

Revision ID: 20260816_000001
Revises: 20260815_000001
Create Date: 2026-08-16

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260816_000001"
down_revision = "20260815_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "social_evaluations",
        sa.Column("ingreso_otros_familiares", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("monto_agua", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("monto_luz", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("monto_gas_domiciliario", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("monto_internet", sa.Float(), nullable=False, server_default="0"),
    )
    op.drop_column("social_evaluations", "monto_servicios_basicos")


def downgrade():
    op.add_column(
        "social_evaluations",
        sa.Column("monto_servicios_basicos", sa.Float(), nullable=False, server_default="0"),
    )
    op.drop_column("social_evaluations", "monto_internet")
    op.drop_column("social_evaluations", "monto_gas_domiciliario")
    op.drop_column("social_evaluations", "monto_luz")
    op.drop_column("social_evaluations", "monto_agua")
    op.drop_column("social_evaluations", "ingreso_otros_familiares")
