"""
Migración: Columnas de cumplimiento legal en social_evaluations
Revision ID: 20260811_000005
Revises: 20260811_000004
Create Date: 2026-08-11

Agrega columnas para cumplir el marco legal boliviano:
  - habeas_data_accepted (Art. 130 CPE + Ley 164)
  - imagen_consent_accepted (uso exclusivo en auditoría)
  - ip_address (trazabilidad técnica)
  - user_agent (dispositivo del evaluador)
"""
from alembic import op
import sqlalchemy as sa

revision = "20260811_000005"
down_revision = "20260811_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "social_evaluations",
        sa.Column("habeas_data_accepted", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("imagen_consent_accepted", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("ip_address", sa.String(45), nullable=True),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("user_agent", sa.String(300), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("social_evaluations", "user_agent")
    op.drop_column("social_evaluations", "ip_address")
    op.drop_column("social_evaluations", "imagen_consent_accepted")
    op.drop_column("social_evaluations", "habeas_data_accepted")
