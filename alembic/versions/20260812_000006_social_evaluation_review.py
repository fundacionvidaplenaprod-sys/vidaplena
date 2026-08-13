"""
Migración: Flujo de revisión/aval de la Evaluación Socioeconómica
Revision ID: 20260812_000006
Revises: 20260811_000005
Create Date: 2026-08-12

Agrega:
  - social_evaluations.estado_revision (PENDIENTE|APROBADO|RECHAZADO)
  - social_evaluations.reviewer_id (FK users.id, quién avaló/rechazó)
  - social_evaluations.revisado_at
  - social_evaluations.motivo_rechazo
  - patients.exonerado_aporte (efecto de una evaluación aprobada)
"""
from alembic import op
import sqlalchemy as sa

revision = "20260812_000006"
down_revision = "20260811_000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "social_evaluations",
        sa.Column("estado_revision", sa.String(20), nullable=False, server_default="PENDIENTE"),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("reviewer_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("revisado_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "social_evaluations",
        sa.Column("motivo_rechazo", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_social_evaluations_reviewer_id",
        "social_evaluations",
        "users",
        ["reviewer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_social_evaluations_estado_revision",
        "social_evaluations",
        ["estado_revision"],
    )

    op.add_column(
        "patients",
        sa.Column("exonerado_aporte", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("patients", "exonerado_aporte")

    op.drop_index("ix_social_evaluations_estado_revision", "social_evaluations")
    op.drop_constraint("fk_social_evaluations_reviewer_id", "social_evaluations", type_="foreignkey")
    op.drop_column("social_evaluations", "motivo_rechazo")
    op.drop_column("social_evaluations", "revisado_at")
    op.drop_column("social_evaluations", "reviewer_id")
    op.drop_column("social_evaluations", "estado_revision")
