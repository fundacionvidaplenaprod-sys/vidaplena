"""add gallery_photos table

Revision ID: 20260803_000001
Revises: 20260802_000003
Create Date: 2026-08-03

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260803_000001"
down_revision = "20260802_000003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "gallery_photos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("caption", sa.String(length=200), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("gallery_photos")
