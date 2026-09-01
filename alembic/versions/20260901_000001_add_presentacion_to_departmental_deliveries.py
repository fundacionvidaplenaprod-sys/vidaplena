"""add presentacion (Vial/Cartucho/Pen) to departmental_insulin_deliveries

El responsable departamental necesita registrar en qué presentación física
entregó la insulina (Vial 10ml, Cartucho 3ml, Pen/Penfild 3ml), además del
tipo y la cantidad. Filas existentes se rellenan con 'Vial 10ml' por
defecto (la presentación más común) para no dejar el campo en blanco.

Revision ID: 20260901_000001
Revises: 20260830_000001
Create Date: 2026-09-01

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260901_000001"
down_revision = "20260830_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "departmental_insulin_deliveries",
        sa.Column("presentacion", sa.String(20), nullable=False, server_default="Vial 10ml"),
    )
    op.create_check_constraint(
        "ck_departmental_delivery_presentacion",
        "departmental_insulin_deliveries",
        "presentacion IN ('Vial 10ml','Cartucho 3ml','Pen/Penfild 3ml')",
    )


def downgrade():
    op.drop_constraint("ck_departmental_delivery_presentacion", "departmental_insulin_deliveries", type_="check")
    op.drop_column("departmental_insulin_deliveries", "presentacion")
