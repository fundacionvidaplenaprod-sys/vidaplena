"""seed NO_REGISTRADO patient state + backfill existing PENDIENTE_DOC rows

NO_REGISTRADO es la mitad de PENDIENTE_DOC que nunca cargó ni CI ni
dirección (solo nombres/apellidos/depto, típicamente precargados desde el
padrón sin que el beneficiario avanzara nada de su carpeta). Antes se
derivaba en tiempo de lectura; ahora es un valor real de patients.estado
(ver app/api/endpoints/patients.py::_estado_inicial_patient).

Revision ID: 20260822_000001
Revises: 20260819_000001
Create Date: 2026-08-22

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260822_000001"
down_revision = "20260819_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "INSERT INTO patient_states (code) VALUES ('NO_REGISTRADO') "
        "ON CONFLICT (code) DO NOTHING"
    )
    op.execute(
        "UPDATE patients SET estado = 'NO_REGISTRADO' "
        "WHERE estado = 'PENDIENTE_DOC' AND ci IS NULL AND direccion IS NULL"
    )


def downgrade():
    op.execute(
        "UPDATE patients SET estado = 'PENDIENTE_DOC' WHERE estado = 'NO_REGISTRADO'"
    )
    op.execute("DELETE FROM patient_states WHERE code = 'NO_REGISTRADO'")
