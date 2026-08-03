"""add site_contact_info table

Revision ID: 20260803_000003
Revises: 20260803_000002
Create Date: 2026-08-03

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260803_000003"
down_revision = "20260803_000002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "site_contact_info",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("email", sa.String(length=160), nullable=True),
        sa.Column("facebook_url", sa.String(length=300), nullable=True),
        sa.Column("instagram_url", sa.String(length=300), nullable=True),
        sa.Column("whatsapp_number", sa.String(length=40), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("site_contact_info")
