"""Ventana de entrega del reparto de insulina en el aviso del portal

`insulin_distributions.entrega_desde` / `entrega_hasta`: al consolidar se indica del … al … se entrega la insulina
(por defecto, del 1 al 10 del mes siguiente); el beneficiario coordina el día y la hora con el(la) responsable de
su departamento.

Revision ID: 20261124_000003
Revises: 20261124_000002
Create Date: 2026-11-24

"""
from alembic import op
import sqlalchemy as sa

revision = "20261124_000003"
down_revision = "20261124_000002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("insulin_distributions", sa.Column("entrega_desde", sa.Date(), nullable=True))
    op.add_column("insulin_distributions", sa.Column("entrega_hasta", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("insulin_distributions", "entrega_hasta")
    op.drop_column("insulin_distributions", "entrega_desde")
