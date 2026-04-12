"""p0_donations_schema_fix

Revision ID: 20260212_000001
Revises: 20260206_000001
Create Date: 2026-02-12 00:00:01.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260212_000001"
down_revision = "20260206_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    donations_columns = {col["name"] for col in inspector.get_columns("donations")}
    if "factor_conversion" not in donations_columns:
        op.add_column(
            "donations",
            sa.Column("factor_conversion", sa.Float(), nullable=True, server_default=sa.text("1.0")),
        )
        op.alter_column("donations", "factor_conversion", server_default=None)

    treatment_columns = {col["name"] for col in inspector.get_columns("patient_treatments")}
    if "dosis_manana" not in treatment_columns:
        op.add_column(
            "patient_treatments",
            sa.Column("dosis_manana", sa.Float(), nullable=True, server_default=sa.text("0.0")),
        )
        op.alter_column("patient_treatments", "dosis_manana", server_default=None)
    if "dosis_tarde" not in treatment_columns:
        op.add_column(
            "patient_treatments",
            sa.Column("dosis_tarde", sa.Float(), nullable=True, server_default=sa.text("0.0")),
        )
        op.alter_column("patient_treatments", "dosis_tarde", server_default=None)
    if "dosis_noche" not in treatment_columns:
        op.add_column(
            "patient_treatments",
            sa.Column("dosis_noche", sa.Float(), nullable=True, server_default=sa.text("0.0")),
        )
        op.alter_column("patient_treatments", "dosis_noche", server_default=None)

    contribution_columns = {col["name"] for col in inspector.get_columns("monthly_contributions")}
    if "observacion_admin" not in contribution_columns:
        op.add_column(
            "monthly_contributions",
            sa.Column("observacion_admin", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    contribution_columns = {col["name"] for col in inspector.get_columns("monthly_contributions")}
    if "observacion_admin" in contribution_columns:
        op.drop_column("monthly_contributions", "observacion_admin")

    treatment_columns = {col["name"] for col in inspector.get_columns("patient_treatments")}
    if "dosis_noche" in treatment_columns:
        op.drop_column("patient_treatments", "dosis_noche")
    if "dosis_tarde" in treatment_columns:
        op.drop_column("patient_treatments", "dosis_tarde")
    if "dosis_manana" in treatment_columns:
        op.drop_column("patient_treatments", "dosis_manana")

    donations_columns = {col["name"] for col in inspector.get_columns("donations")}
    if "factor_conversion" in donations_columns:
        op.drop_column("donations", "factor_conversion")
