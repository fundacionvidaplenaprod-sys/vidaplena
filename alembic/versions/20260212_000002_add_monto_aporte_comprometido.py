"""add_monto_aporte_comprometido

Revision ID: 20260212_000002
Revises: 20260212_000001
Create Date: 2026-02-12 00:00:02.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260212_000002"
down_revision = "20260212_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    patient_columns = {col["name"] for col in inspector.get_columns("patients")}
    if "monto_aporte_comprometido" not in patient_columns:
        op.add_column(
            "patients",
            sa.Column("monto_aporte_comprometido", sa.Numeric(12, 2), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    patient_columns = {col["name"] for col in inspector.get_columns("patients")}
    if "monto_aporte_comprometido" in patient_columns:
        op.drop_column("patients", "monto_aporte_comprometido")
