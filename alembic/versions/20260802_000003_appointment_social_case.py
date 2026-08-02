"""appointments: add social-case exemption columns (eximido_por/at, motivo_exencion)

Revision ID: 20260802_000003
Revises: 20260802_000002
Create Date: 2026-08-02

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260802_000003"
down_revision = "20260802_000002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "appointments",
        sa.Column("eximido_por", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column("eximido_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column("motivo_exencion", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("appointments", "motivo_exencion")
    op.drop_column("appointments", "eximido_at")
    op.drop_column("appointments", "eximido_por")
