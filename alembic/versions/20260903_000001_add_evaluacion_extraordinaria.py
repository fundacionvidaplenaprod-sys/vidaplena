"""add evaluación social extraordinaria (imposibilidad de llenado digital)

Agrega la vía alternativa para EVALUADOR_SOCIAL/SUPER_ADMIN: cuando un
beneficiario está imposibilitado de completar el formulario digital
estándar, se registra la evaluación con una justificación explícita, la
aceptación de responsabilidad de quien la registra, y un informe basado en
una entrevista telefónica (reutiliza entrevista_notas) en vez del
cuestionario completo de ingresos/vivienda/servicios.

Revision ID: 20260903_000001
Revises: 20260902_000001
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260903_000001"
down_revision = "20260902_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "social_evaluations",
        sa.Column("es_extraordinaria", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("justificacion_extraordinaria", sa.Text(), nullable=True),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("responsabilidad_aceptada", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("social_evaluations", "responsabilidad_aceptada")
    op.drop_column("social_evaluations", "justificacion_extraordinaria")
    op.drop_column("social_evaluations", "es_extraordinaria")
