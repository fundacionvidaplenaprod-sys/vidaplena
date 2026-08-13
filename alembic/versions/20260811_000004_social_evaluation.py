"""
Migración: Tabla social_evaluations y rol EVALUADOR_SOCIAL
Revision ID: 20260811_000004
Revises: 20260803_000003
Create Date: 2026-08-11
"""
from alembic import op
import sqlalchemy as sa

revision = "20260811_000004"
down_revision = "20260803_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Actualizar el CheckConstraint del rol en la tabla users
    #    para incluir EVALUADOR_SOCIAL
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('SUPER_ADMIN','REGISTRADOR','PACIENTE','EVALUADOR_SOCIAL')",
    )

    # 2. Crear la tabla social_evaluations
    op.create_table(
        "social_evaluations",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("patient_id", sa.BigInteger(), nullable=False),
        sa.Column("evaluator_id", sa.BigInteger(), nullable=True),

        # Demográficos
        sa.Column("departamento", sa.String(80), nullable=False),
        sa.Column("integrantes_hogar", sa.Integer(), nullable=False),
        sa.Column("dependientes", sa.Integer(), nullable=False, server_default="0"),

        # Vivienda
        sa.Column("tipo_vivienda", sa.String(60), nullable=False),
        sa.Column("monto_alquiler", sa.Float(), nullable=False, server_default="0"),

        # Salud e Ingresos
        sa.Column("tiene_seguro", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("tipo_seguro", sa.String(80), nullable=True),
        sa.Column("condicion_laboral", sa.String(80), nullable=True),
        sa.Column("ingreso_titular", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ingreso_conyuge", sa.Float(), nullable=False, server_default="0"),

        # Resultados del motor de categorización
        sa.Column("ingreso_per_capita", sa.Float(), nullable=False, server_default="0"),
        sa.Column("categoria_asignada", sa.String(10), nullable=False),
        sa.Column("estado_alerta", sa.String(50), nullable=False, server_default="NORMAL"),

        # Evidencias (URLs de Firebase Storage)
        sa.Column("foto_ci_url", sa.String(500), nullable=True),
        sa.Column("foto_fachada_url", sa.String(500), nullable=True),
        sa.Column("foto_sala_url", sa.String(500), nullable=True),
        sa.Column("foto_dormitorio_url", sa.String(500), nullable=True),
        sa.Column("firma_digital_url", sa.String(500), nullable=True),

        # Auditoría
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),

        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("patient_id", name="uq_social_evaluations_patient_id"),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["evaluator_id"], ["users.id"], ondelete="SET NULL"
        ),
    )

    # Índice para búsquedas por evaluador
    op.create_index(
        "ix_social_evaluations_evaluator_id",
        "social_evaluations",
        ["evaluator_id"],
    )
    # Índice para filtrar por alerta
    op.create_index(
        "ix_social_evaluations_estado_alerta",
        "social_evaluations",
        ["estado_alerta"],
    )


def downgrade() -> None:
    op.drop_index("ix_social_evaluations_estado_alerta", "social_evaluations")
    op.drop_index("ix_social_evaluations_evaluator_id", "social_evaluations")
    op.drop_table("social_evaluations")

    # Revertir el CheckConstraint del rol
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('SUPER_ADMIN','REGISTRADOR','PACIENTE')",
    )
