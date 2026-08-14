"""patients: add estado_beneficio y evaluacion_bloqueada_hasta

Soporte para el rechazo en dos niveles de la evaluación socioeconómica:
  - Nivel 1 (rechazo estándar): cooldown temporal (evaluacion_bloqueada_hasta).
  - Nivel 2 (rechazo por falsedad): suspensión permanente (estado_beneficio).

Revision ID: 20260814_000004
Revises: 20260814_000003
Create Date: 2026-08-14

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260814_000004"
down_revision = "20260814_000003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "patients",
        sa.Column("estado_beneficio", sa.String(20), nullable=False, server_default="ACTIVO"),
    )
    op.add_column(
        "patients",
        sa.Column("evaluacion_bloqueada_hasta", sa.Date(), nullable=True),
    )


def downgrade():
    op.drop_column("patients", "evaluacion_bloqueada_hasta")
    op.drop_column("patients", "estado_beneficio")
