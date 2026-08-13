"""social_evaluations: add ayuda de otra institucion y deudas que comprometen ingresos

Revision ID: 20260813_000001
Revises: 20260812_000007
Create Date: 2026-08-13

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260813_000001"
down_revision = "20260812_000007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "social_evaluations",
        sa.Column("recibe_ayuda_otra_institucion", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("nombre_institucion_ayuda", sa.String(160), nullable=True),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("tiene_deudas_comprometen_ingresos", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("social_evaluations", "tiene_deudas_comprometen_ingresos")
    op.drop_column("social_evaluations", "nombre_institucion_ayuda")
    op.drop_column("social_evaluations", "recibe_ayuda_otra_institucion")
