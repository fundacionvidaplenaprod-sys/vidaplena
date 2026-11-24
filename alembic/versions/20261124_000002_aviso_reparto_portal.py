"""Aviso del reparto de insulina en el Portal del Beneficiario

- `insulin_distributions.aviso_mensaje`: indicaciones para los beneficiarios que acompañan el aviso (p. ej.
  dónde y cuándo recoger la insulina), escritas al consolidar.
- Nueva tabla `insulin_distribution_notices`: al consolidar un reparto, un aviso por beneficiario con ficha
  (el Registro Asistido no tiene portal) y cuándo lo vio (`visto_at`, al pulsar «Entendido»).

Revision ID: 20261124_000002
Revises: 20261124_000001
Create Date: 2026-11-24

"""
from alembic import op
import sqlalchemy as sa

revision = "20261124_000002"
down_revision = "20261124_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("insulin_distributions", sa.Column("aviso_mensaje", sa.Text(), nullable=True))
    op.create_table(
        "insulin_distribution_notices",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "distribution_id", sa.BigInteger(),
            sa.ForeignKey("insulin_distributions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("patient_id", sa.BigInteger(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("visto_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("distribution_id", "patient_id", name="uq_insulin_distribution_notice"),
    )
    op.create_index("ix_insulin_distribution_notices_patient_id", "insulin_distribution_notices", ["patient_id"])


def downgrade():
    op.drop_index("ix_insulin_distribution_notices_patient_id", table_name="insulin_distribution_notices")
    op.drop_table("insulin_distribution_notices")
    op.drop_column("insulin_distributions", "aviso_mensaje")
