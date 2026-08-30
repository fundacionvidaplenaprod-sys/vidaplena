"""add insulin_shipments (coordinador nacional -> responsable departamental)

Etapa 1 del flujo de insulina: el COORDINADOR_NACIONAL registra qué insulina
(tipo/cantidad) le envió a cada RESPONSABLE_DEPARTAMENTAL, con fecha libre
(puede estar registrando un envío que ya ocurrió). Es solo un log de
control/auditoría, igual que departmental_insulin_deliveries (etapa 2, del
responsable al beneficiario) — NO afecta stock de almacén.

Revision ID: 20260830_000001
Revises: 20260827_000002
Create Date: 2026-08-30

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260830_000001"
down_revision = "20260827_000002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "insulin_shipments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("recipient_user_id", sa.BigInteger(), nullable=False),
        sa.Column("depto", sa.String(80), nullable=False),
        sa.Column("insulin_type", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Text(), nullable=False),
        sa.Column("shipment_date", sa.Date(), nullable=False, server_default=sa.func.current_date()),
        sa.Column("recorded_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_insulin_shipments_recipient_user_id", "insulin_shipments", ["recipient_user_id"])
    op.create_index("ix_insulin_shipments_depto", "insulin_shipments", ["depto"])
    op.create_index("ix_insulin_shipments_shipment_date", "insulin_shipments", ["shipment_date"])


def downgrade():
    op.drop_index("ix_insulin_shipments_shipment_date", table_name="insulin_shipments")
    op.drop_index("ix_insulin_shipments_depto", table_name="insulin_shipments")
    op.drop_index("ix_insulin_shipments_recipient_user_id", table_name="insulin_shipments")
    op.drop_table("insulin_shipments")
