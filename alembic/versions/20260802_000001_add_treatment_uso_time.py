"""Add tiempo_uso_meses and tiempo_uso_anios to patient_treatments

Revision ID: 20260802_000001
Revises: 20260801_000001
Create Date: 2026-08-02

Adds two optional integer columns to patient_treatments to record
how long a patient has been using a specific insulin treatment.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260802_000001"
down_revision = "20260801_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "patient_treatments",
        sa.Column("tiempo_uso_meses", sa.Integer(), nullable=True),
    )
    op.add_column(
        "patient_treatments",
        sa.Column("tiempo_uso_anios", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column("patient_treatments", "tiempo_uso_anios")
    op.drop_column("patient_treatments", "tiempo_uso_meses")
