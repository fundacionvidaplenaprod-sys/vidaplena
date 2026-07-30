"""seed HABILITADO patient state (missing from initial seed)

Revision ID: 20260730_000001
Revises: 20260719_000001
Create Date: 2026-07-30

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260730_000001"
down_revision = "20260719_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "INSERT INTO patient_states (code) VALUES ('HABILITADO') "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade():
    op.execute("DELETE FROM patient_states WHERE code = 'HABILITADO'")
