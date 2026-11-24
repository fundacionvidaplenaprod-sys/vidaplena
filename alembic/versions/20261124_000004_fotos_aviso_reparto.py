"""Fotos del beneficiario en el aviso del reparto: insulinas ya usadas y hemoglobina glucosilada

En `insulin_distribution_notices`, una foto de cada una por reparto (la puede reemplazar) y cuándo la subió:
- `foto_envases_url` / `foto_envases_at`: los envases vacíos de su entrega anterior (reglamento, art. 17 b).
- `foto_hba1c_url` / `foto_hba1c_at`: su último resultado de HbA1c (reglamento, art. 8; imagen o PDF).

Revision ID: 20261124_000004
Revises: 20261124_000003
Create Date: 2026-11-24

"""
from alembic import op
import sqlalchemy as sa

revision = "20261124_000004"
down_revision = "20261124_000003"
branch_labels = None
depends_on = None

COLUMNAS = ("foto_envases", "foto_hba1c")


def upgrade():
    for col in COLUMNAS:
        op.add_column("insulin_distribution_notices", sa.Column(f"{col}_url", sa.Text(), nullable=True))
        op.add_column("insulin_distribution_notices", sa.Column(f"{col}_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    for col in reversed(COLUMNAS):
        op.drop_column("insulin_distribution_notices", f"{col}_at")
        op.drop_column("insulin_distribution_notices", f"{col}_url")
