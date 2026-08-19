"""social_evaluations: sugerencia de exclusión del programa (categoría BAJA)

- exclusion_sugerida: el evaluador puede marcarla al aprobar con BAJA si el
  beneficiario cuenta con medios económicos suficientes para sostener su
  condición sin la Fundación. Es solo una sugerencia, no cambia el estado
  del beneficiario automáticamente.
- motivo_exclusion_sugerida: justificación obligatoria cuando se marca.

Revision ID: 20260819_000001
Revises: 20260816_000001
Create Date: 2026-08-19

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260819_000001"
down_revision = "20260816_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "social_evaluations",
        sa.Column("exclusion_sugerida", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("motivo_exclusion_sugerida", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("social_evaluations", "motivo_exclusion_sugerida")
    op.drop_column("social_evaluations", "exclusion_sugerida")
