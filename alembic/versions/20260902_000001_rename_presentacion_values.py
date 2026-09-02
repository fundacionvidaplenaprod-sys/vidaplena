"""rename presentacion values (Vial 10ml -> Frasco 10ml, Pen/Penfild 3ml -> Pen 3ml)

La Fundación pidió renombrar 2 de las 3 presentaciones físicas de insulina:
'Vial 10ml' -> 'Frasco 10ml' y 'Pen/Penfild 3ml' -> 'Pen 3ml' ('Cartucho
3ml' no cambia). Se actualizan los datos existentes en ambas tablas antes
de reemplazar los CHECK constraints y el default de columna, para no dejar
filas viejas violando la nueva restricción.

Revision ID: 20260902_000001
Revises: 20260901_000002
Create Date: 2026-09-02

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260902_000001"
down_revision = "20260901_000002"
branch_labels = None
depends_on = None

TABLES = ["departmental_insulin_deliveries", "insulin_shipments"]
CONSTRAINTS = {
    "departmental_insulin_deliveries": "ck_departmental_delivery_presentacion",
    "insulin_shipments": "ck_insulin_shipment_presentacion",
}
OLD_VALUES = "'Vial 10ml','Cartucho 3ml','Pen/Penfild 3ml'"
NEW_VALUES = "'Frasco 10ml','Cartucho 3ml','Pen 3ml'"


def upgrade():
    for table in TABLES:
        constraint = CONSTRAINTS[table]
        op.drop_constraint(constraint, table, type_="check")
        op.execute(f"UPDATE {table} SET presentacion = 'Frasco 10ml' WHERE presentacion = 'Vial 10ml'")
        op.execute(f"UPDATE {table} SET presentacion = 'Pen 3ml' WHERE presentacion = 'Pen/Penfild 3ml'")
        op.alter_column(table, "presentacion", server_default="Frasco 10ml")
        op.create_check_constraint(constraint, table, f"presentacion IN ({NEW_VALUES})")


def downgrade():
    for table in TABLES:
        constraint = CONSTRAINTS[table]
        op.drop_constraint(constraint, table, type_="check")
        op.execute(f"UPDATE {table} SET presentacion = 'Vial 10ml' WHERE presentacion = 'Frasco 10ml'")
        op.execute(f"UPDATE {table} SET presentacion = 'Pen/Penfild 3ml' WHERE presentacion = 'Pen 3ml'")
        op.alter_column(table, "presentacion", server_default="Vial 10ml")
        op.create_check_constraint(constraint, table, f"presentacion IN ({OLD_VALUES})")
