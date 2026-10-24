"""La insulina «Protamina» pasa a llamarse «Mixta».

Solo cambia el nombre guardado en los tratamientos de las fichas
(`patient_treatments.nombre`); es el único lugar donde se guarda. El catálogo
sigue reconociendo «protamina» como alias, así que un Excel o una ficha con el
nombre anterior se lee igual.

Revision ID: 20261023_000001
Revises: 20261020_000001
"""
from alembic import op

revision = "20261023_000001"
down_revision = "20261020_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE patient_treatments SET nombre = 'Mixta' "
        "WHERE lower(trim(nombre)) = 'protamina'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE patient_treatments SET nombre = 'Protamina' "
        "WHERE lower(trim(nombre)) = 'mixta'"
    )
