"""add presentacion (Vial/Cartucho/Pen) to insulin_shipments

El coordinador nacional también necesita registrar en qué presentación
física envía la insulina al responsable departamental (Vial 10ml,
Cartucho 3ml, Pen/Penfild 3ml), igual que ya se hizo para
departmental_insulin_deliveries. Filas existentes se rellenan con
'Vial 10ml' por defecto (la presentación más común) para no dejar el
campo en blanco.

Revision ID: 20260901_000002
Revises: 20260901_000001
Create Date: 2026-09-01

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260901_000002"
down_revision = "20260901_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "insulin_shipments",
        sa.Column("presentacion", sa.String(20), nullable=False, server_default="Vial 10ml"),
    )
    op.create_check_constraint(
        "ck_insulin_shipment_presentacion",
        "insulin_shipments",
        "presentacion IN ('Vial 10ml','Cartucho 3ml','Pen/Penfild 3ml')",
    )


def downgrade():
    op.drop_constraint("ck_insulin_shipment_presentacion", "insulin_shipments", type_="check")
    op.drop_column("insulin_shipments", "presentacion")
