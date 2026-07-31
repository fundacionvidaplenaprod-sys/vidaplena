"""SAPAM: doctor_blocked_days + appointments tables

Revision ID: 20260730_000002
Revises: 20260730_000001
Create Date: 2026-07-30

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260730_000002"
down_revision = "20260730_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "doctor_blocked_days",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("fecha", sa.Date(), nullable=False, unique=True),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "appointments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("nombres", sa.String(120), nullable=False),
        sa.Column("ap_paterno", sa.String(80), nullable=False),
        sa.Column("ap_materno", sa.String(80), nullable=True),
        sa.Column("ci", sa.String(32), nullable=False),
        sa.Column("fecha_nac", sa.Date(), nullable=False),
        sa.Column("fecha_cita", sa.Date(), nullable=False),
        sa.Column("hora_cita", sa.Time(), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("url_comprobante", sa.String(500), nullable=True),
        sa.Column("ocr_monto_detectado", sa.Numeric(12, 2), nullable=True),
        sa.Column("ocr_fecha_detectada", sa.Date(), nullable=True),
        sa.Column("ocr_hora_detectada", sa.Time(), nullable=True),
        sa.Column("motivo_rechazo", sa.Text(), nullable=True),
        sa.Column("security_code", sa.String(32), nullable=True, unique=True),
        sa.Column("nota_consulta", sa.Text(), nullable=True),
        sa.Column("nota_consulta_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nota_consulta_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("estado IN ('CONFIRMADA','RECHAZADA')", name="ck_appointment_estado"),
    )

    # Evita doble-reserva del mismo horario: solo puede existir una fila
    # CONFIRMADA por (fecha_cita, hora_cita). Las filas RECHAZADA no ocupan cupo.
    op.execute(
        "CREATE UNIQUE INDEX uq_appointments_slot_confirmada "
        "ON appointments (fecha_cita, hora_cita) WHERE estado = 'CONFIRMADA'"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_appointments_slot_confirmada")
    op.drop_table("appointments")
    op.drop_table("doctor_blocked_days")
