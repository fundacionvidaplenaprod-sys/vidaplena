"""director_insulin_deliveries: vínculo al beneficiario, presentación y marca

El cuaderno de la Directora pasa de texto libre a un registro estructurado: al elegir al
beneficiario de la lista queda ligado a su ficha (`patient_id`), y por cada insulina se anota
la presentación entregada y la marca (Lantus, Toujeo, ...). Los tres campos son opcionales:
las entregas ya registradas y las de personas fuera del padrón siguen siendo válidas.

Revision ID: 20261020_000001
Revises: 20260908_000001
Create Date: 2026-10-20

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20261020_000001"
down_revision = "20260908_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("director_insulin_deliveries", sa.Column("patient_id", sa.BigInteger(), nullable=True))
    op.add_column("director_insulin_deliveries", sa.Column("presentacion", sa.String(20), nullable=True))
    op.add_column("director_insulin_deliveries", sa.Column("marca", sa.String(60), nullable=True))
    op.create_foreign_key(
        "fk_director_deliveries_patient_id_patients",
        "director_insulin_deliveries",
        "patients",
        ["patient_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_director_delivery_presentacion",
        "director_insulin_deliveries",
        "presentacion IS NULL OR presentacion IN ('Frasco 10ml','Cartucho 3ml','Pen 3ml')",
    )
    op.create_index("ix_director_deliveries_patient_id", "director_insulin_deliveries", ["patient_id"])
    op.create_index("ix_director_deliveries_delivery_date", "director_insulin_deliveries", ["delivery_date"])


def downgrade():
    op.drop_index("ix_director_deliveries_delivery_date", table_name="director_insulin_deliveries")
    op.drop_index("ix_director_deliveries_patient_id", table_name="director_insulin_deliveries")
    op.drop_constraint("ck_director_delivery_presentacion", "director_insulin_deliveries", type_="check")
    op.drop_constraint("fk_director_deliveries_patient_id_patients", "director_insulin_deliveries", type_="foreignkey")
    op.drop_column("director_insulin_deliveries", "marca")
    op.drop_column("director_insulin_deliveries", "presentacion")
    op.drop_column("director_insulin_deliveries", "patient_id")
