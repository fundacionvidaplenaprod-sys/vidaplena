"""Almacén: ingreso por Excel de la donación y reparto de insulina consolidado

- `donations`: presentación en ml y concentración (UI/ml) del Excel de la donación (packing list).
- Nueva tabla `donation_intakes`: cada Excel ingresado (archivo, huella sha256, filas, envases, UI) y
  `donation_lots.intake_id`, para saber de qué ingreso salió cada lote.
- Nuevas tablas `insulin_distributions`, `insulin_distribution_items` e `insulin_distribution_swaps`: el
  reparto calculado con el motor del reporte, sus líneas (beneficiario, tratamiento, lote, envases) y los
  intercambios equivalentes hechos antes de consolidarlo.

Revision ID: 20261124_000001
Revises: 20261025_000001
Create Date: 2026-11-24

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261124_000001"
down_revision = "20261025_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("donations", sa.Column("presentacion_ml", sa.Float(), nullable=True))
    op.add_column("donations", sa.Column("concentracion_ui_ml", sa.Integer(), nullable=True))

    op.create_table(
        "donation_intakes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("archivo", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("filas", sa.Integer(), nullable=False),
        sa.Column("envases", sa.Integer(), nullable=False),
        sa.Column("ui_total", sa.Float(), nullable=False),
        sa.Column("created_by_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column(
        "donation_lots",
        sa.Column(
            "intake_id", sa.BigInteger(), sa.ForeignKey("donation_intakes.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.create_index("ix_donation_lots_intake_id", "donation_lots", ["intake_id"])

    op.create_table(
        "insulin_distributions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("estado", sa.String(16), nullable=False, server_default="BORRADOR"),
        sa.Column("dias", sa.Integer(), nullable=False),
        sa.Column("resultado", postgresql.JSONB(), nullable=False),
        sa.Column("propuesta", postgresql.JSONB(), nullable=False),
        sa.Column("stock_calculado", postgresql.JSONB(), nullable=False),
        sa.Column("created_by_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "consolidated_by_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("consolidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('BORRADOR','CONSOLIDADO','DESCARTADO')", name="ck_insulin_distribution_estado"
        ),
    )
    op.create_index("ix_insulin_distributions_estado", "insulin_distributions", ["estado"])

    op.create_table(
        "insulin_distribution_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "distribution_id",
            sa.BigInteger(),
            sa.ForeignKey("insulin_distributions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("beneficiario_id", sa.BigInteger(), nullable=False),
        sa.Column("patient_id", sa.BigInteger(), sa.ForeignKey("patients.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "assisted_registration_id",
            sa.BigInteger(),
            sa.ForeignKey("assisted_registrations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("insulina", sa.String(40), nullable=False),
        sa.Column("lot_id", sa.BigInteger(), sa.ForeignKey("donation_lots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("envases", sa.Integer(), nullable=False),
        sa.Column("ui", sa.Float(), nullable=False),
        sa.UniqueConstraint(
            "distribution_id", "beneficiario_id", "insulina", "lot_id", name="uq_insulin_distribution_item"
        ),
        sa.CheckConstraint("envases > 0", name="ck_insulin_distribution_item_envases"),
    )
    op.create_index("ix_insulin_distribution_items_distribution", "insulin_distribution_items", ["distribution_id"])
    op.create_index("ix_insulin_distribution_items_patient", "insulin_distribution_items", ["patient_id"])

    op.create_table(
        "insulin_distribution_swaps",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "distribution_id",
            sa.BigInteger(),
            sa.ForeignKey("insulin_distributions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("beneficiario_a", sa.BigInteger(), nullable=False),
        sa.Column("insulina_a", sa.String(40), nullable=False),
        sa.Column("lot_a_id", sa.BigInteger(), sa.ForeignKey("donation_lots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("envases_a", sa.Integer(), nullable=False),
        sa.Column("beneficiario_b", sa.BigInteger(), nullable=False),
        sa.Column("insulina_b", sa.String(40), nullable=False),
        sa.Column("lot_b_id", sa.BigInteger(), sa.ForeignKey("donation_lots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("envases_b", sa.Integer(), nullable=False),
        sa.Column("ui", sa.Float(), nullable=False),
        sa.Column("created_by_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_insulin_distribution_swaps_distribution", "insulin_distribution_swaps", ["distribution_id"])


def downgrade():
    op.drop_index("ix_insulin_distribution_swaps_distribution", table_name="insulin_distribution_swaps")
    op.drop_table("insulin_distribution_swaps")
    op.drop_index("ix_insulin_distribution_items_patient", table_name="insulin_distribution_items")
    op.drop_index("ix_insulin_distribution_items_distribution", table_name="insulin_distribution_items")
    op.drop_table("insulin_distribution_items")
    op.drop_index("ix_insulin_distributions_estado", table_name="insulin_distributions")
    op.drop_table("insulin_distributions")
    op.drop_index("ix_donation_lots_intake_id", table_name="donation_lots")
    op.drop_column("donation_lots", "intake_id")
    op.drop_table("donation_intakes")
    op.drop_column("donations", "concentracion_ui_ml")
    op.drop_column("donations", "presentacion_ml")
