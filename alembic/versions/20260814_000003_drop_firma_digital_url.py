"""social_evaluations: drop firma_digital_url (firma digital eliminada del flujo)

La evaluación socioeconómica ya no pide firma digital al beneficiario
(se reemplazó por el aviso de entrevista virtual). No hay evaluaciones
reales que dependan de esta columna todavía.

Revision ID: 20260814_000003
Revises: 20260814_000002
Create Date: 2026-08-14

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260814_000003"
down_revision = "20260814_000002"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("social_evaluations", "firma_digital_url")


def downgrade():
    op.add_column(
        "social_evaluations",
        sa.Column("firma_digital_url", sa.String(500), nullable=True),
    )
