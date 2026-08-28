"""add metodo_pago (VOUCHER/EFECTIVO) to monthly_contributions

Los beneficiarios del área rural suelen pagar su aporte en efectivo
directamente a la doctora en campo, sin generar ningún voucher/QR digital.
Antes, `url_comprobante` era NOT NULL, así que no existía forma de registrar
ese pago sin inventar un archivo. Ahora `monthly_contributions` distingue el
método de pago; para EFECTIVO, `url_comprobante` puede quedar en NULL.

Revision ID: 20260827_000001
Revises: 20260822_000001
Create Date: 2026-08-27

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260827_000001"
down_revision = "20260822_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "monthly_contributions",
        sa.Column("metodo_pago", sa.String(20), nullable=False, server_default="VOUCHER"),
    )
    op.alter_column("monthly_contributions", "url_comprobante", nullable=True)
    op.create_check_constraint(
        "ck_contrib_metodo_pago",
        "monthly_contributions",
        "metodo_pago IN ('VOUCHER','EFECTIVO')",
    )
    op.create_check_constraint(
        "ck_contrib_efectivo_sin_comprobante",
        "monthly_contributions",
        "metodo_pago = 'EFECTIVO' OR url_comprobante IS NOT NULL",
    )


def downgrade():
    op.drop_constraint("ck_contrib_efectivo_sin_comprobante", "monthly_contributions", type_="check")
    op.drop_constraint("ck_contrib_metodo_pago", "monthly_contributions", type_="check")
    op.execute(
        "UPDATE monthly_contributions SET url_comprobante = '' WHERE url_comprobante IS NULL"
    )
    op.alter_column("monthly_contributions", "url_comprobante", nullable=False)
    op.drop_column("monthly_contributions", "metodo_pago")
