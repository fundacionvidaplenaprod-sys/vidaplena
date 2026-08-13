"""
Migración: Registro de entrevista virtual previa al veredicto
Revision ID: 20260812_000007
Revises: 20260812_000006
Create Date: 2026-08-12

El evaluador social se reúne con el beneficiario por medios externos al
sistema (videollamada, etc.) antes de poder avalar o rechazar la
evaluación. Estas columnas registran esa entrevista.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260812_000007"
down_revision = "20260812_000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "social_evaluations",
        sa.Column("entrevista_realizada", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("entrevista_fecha", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("entrevista_notas", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("social_evaluations", "entrevista_notas")
    op.drop_column("social_evaluations", "entrevista_fecha")
    op.drop_column("social_evaluations", "entrevista_realizada")
