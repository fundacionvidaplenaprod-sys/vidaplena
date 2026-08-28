"""add RESPONSABLE_DEPARTAMENTAL / COORDINADOR_NACIONAL roles + departmental insulin deliveries

Nuevos roles para el seguimiento de campo por departamento:
  - RESPONSABLE_DEPARTAMENTAL: ve/actúa solo sobre beneficiarios de su propio
    departamento (users.depto_asignado).
  - COORDINADOR_NACIONAL: misma visibilidad pero a nivel nacional, estrictamente
    de solo lectura (no puede registrar entregas de insulina).

departmental_insulin_deliveries es un log de control (fecha/cantidad/tipo),
NO afecta stock de almacén. A diferencia de director_insulin_deliveries
(flujo aislado de "la Directora", sin patient_id por diseño), esta tabla
queda ligada al beneficiario real vía FK para poder acotar por departamento.

Revision ID: 20260827_000002
Revises: 20260827_000001
Create Date: 2026-08-27

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260827_000002"
down_revision = "20260827_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_users_role", "users", type_="check")
    # 'RESPONSABLE_DEPARTAMENTAL' (26 caracteres) no entra en el VARCHAR(20)
    # original — se amplía antes de permitir el valor vía el constraint.
    op.alter_column("users", "role", type_=sa.String(40))
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('SUPER_ADMIN','REGISTRADOR','PACIENTE','EVALUADOR_SOCIAL',"
        "'RESPONSABLE_DEPARTAMENTAL','COORDINADOR_NACIONAL')",
    )

    op.add_column("users", sa.Column("depto_asignado", sa.String(80), nullable=True))

    op.create_table(
        "departmental_insulin_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("patient_id", sa.BigInteger(), nullable=False),
        sa.Column("depto", sa.String(80), nullable=False),
        sa.Column("insulin_type", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Text(), nullable=False),
        sa.Column("delivery_date", sa.Date(), nullable=False, server_default=sa.func.current_date()),
        sa.Column("recorded_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_departmental_insulin_deliveries_depto", "departmental_insulin_deliveries", ["depto"])
    op.create_index("ix_departmental_insulin_deliveries_patient_id", "departmental_insulin_deliveries", ["patient_id"])
    op.create_index("ix_departmental_insulin_deliveries_delivery_date", "departmental_insulin_deliveries", ["delivery_date"])


def downgrade():
    op.drop_index("ix_departmental_insulin_deliveries_delivery_date", table_name="departmental_insulin_deliveries")
    op.drop_index("ix_departmental_insulin_deliveries_patient_id", table_name="departmental_insulin_deliveries")
    op.drop_index("ix_departmental_insulin_deliveries_depto", table_name="departmental_insulin_deliveries")
    op.drop_table("departmental_insulin_deliveries")

    op.drop_column("users", "depto_asignado")

    op.drop_constraint("ck_users_role", "users", type_="check")
    op.alter_column("users", "role", type_=sa.String(20))
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('SUPER_ADMIN','REGISTRADOR','PACIENTE','EVALUADOR_SOCIAL')",
    )
