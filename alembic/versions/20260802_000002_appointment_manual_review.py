"""appointments: add manual review columns (revisado_manualmente_por/at)

Revision ID: 20260802_000002
Revises: 20260802_000001
Create Date: 2026-08-02

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260802_000002"
down_revision = "20260802_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "appointments",
        sa.Column("revisado_manualmente_por", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column(
        "appointments",
        sa.Column("revisado_manualmente_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("appointments", "revisado_manualmente_at")
    op.drop_column("appointments", "revisado_manualmente_por")
