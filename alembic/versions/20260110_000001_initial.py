"""Initial schema for VIDAPLENA

Revision ID: 20260110_000001
Revises: 
Create Date: 2026-01-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260110_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "patient_states",
        sa.Column("code", sa.Text(), primary_key=True),
    )

    op.create_table(
        "complication_types",
        sa.Column("code", sa.Text(), primary_key=True),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("email", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="ACTIVO"),
        sa.Column("last_login", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint(
            "role IN ('SUPER_ADMIN','REGISTRADOR','PACIENTE')", name="ck_users_role"
        ),
    )

    op.create_table(
        "patients",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), unique=True),
        sa.Column("ci", sa.String(length=32), nullable=False, unique=True),
        sa.Column("nombres", sa.String(length=120), nullable=False),
        sa.Column("ap_paterno", sa.String(length=80), nullable=False),
        sa.Column("ap_materno", sa.String(length=80)),
        sa.Column("fecha_nac", sa.Date(), nullable=False),
        sa.Column("peso", sa.Numeric(5, 2)),
        sa.Column("altura", sa.Numeric(5, 2)),
        sa.Column("tipo_sangre", sa.String(length=8)),
        sa.Column("depto", sa.String(length=80)),
        sa.Column("municipio", sa.String(length=80)),
        sa.Column("zona", sa.String(length=120)),
        sa.Column("direccion", sa.Text()),
        sa.Column("email", sa.String(length=160)),
        sa.Column("tel_contacto", sa.String(length=40)),
        sa.Column("tel_referencia", sa.String(length=40)),
        sa.Column("estado", sa.String(length=32), nullable=False, server_default="PENDIENTE_DOC"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["estado"], ["patient_states.code"]),
    )
    op.create_index("idx_patients_estado", "patients", ["estado"])
    op.create_index("idx_patients_depto_muni", "patients", ["depto", "municipio"])

    op.create_table(
        "tutors",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("patient_id", sa.BigInteger(), unique=True),
        sa.Column("nombres", sa.String(length=120), nullable=False),
        sa.Column("apellidos", sa.String(length=160), nullable=False),
        sa.Column("ci", sa.String(length=32), nullable=False, unique=True),
        sa.Column("direccion", sa.Text()),
        sa.Column("telefonos", sa.String(length=160)),
        sa.Column("email", sa.String(length=160)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "patient_medical",
        sa.Column("patient_id", sa.BigInteger(), primary_key=True),
        sa.Column("tipo_diabetes", sa.String(length=50), nullable=False),
        sa.Column("tiempo_enfermedad", sa.String(length=50)),
        sa.Column("notas", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "patient_complications",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("patient_id", sa.BigInteger(), nullable=False),
        sa.Column("complication_code", sa.Text(), nullable=False),
        sa.Column("detalle", sa.Text()),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["complication_code"], ["complication_types.code"]),
    )

    op.create_table(
        "patient_treatments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("patient_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("dosis", sa.String(length=80)),
        sa.Column("frecuencia", sa.String(length=80)),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "tipo IN ('INSULINA','ADO','OTRO_MED','INSUMO')",
            name="ck_patient_treatments_tipo",
        ),
    )

    op.create_table(
        "patient_documents",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("patient_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo", sa.String(length=32), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("mime", sa.String(length=64)),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("fecha_carga", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("valido", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("observado", sa.Text()),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("patient_id", "tipo", name="uq_patient_document_tipo"),
        sa.CheckConstraint(
            "tipo IN ('CI_PACIENTE','CI_TUTOR','CI_MENOR','CERT_MED','FOTO_PAC','FOTO_TUTOR','DECL_JURADA')",
            name="ck_patient_documents_tipo",
        ),
    )

    op.create_table(
        "voluntary_pledges",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("patient_id", sa.BigInteger(), nullable=False),
        sa.Column("monto_compromiso", sa.Numeric(12, 2), nullable=False),
        sa.Column("fecha_firma", sa.Date(), nullable=False),
        sa.Column("url_pdf", sa.Text(), nullable=False),
        sa.Column("vigente", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.CheckConstraint("monto_compromiso >= 50", name="ck_pledge_min_amount"),
        sa.UniqueConstraint("patient_id", "vigente", name="uq_pledge_patient_vigente"),
    )

    op.create_table(
        "monthly_contributions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("patient_id", sa.BigInteger(), nullable=False),
        sa.Column("periodo", sa.String(length=7), nullable=False),
        sa.Column("fecha_pago", sa.Date(), nullable=False),
        sa.Column("monto", sa.Numeric(12, 2), nullable=False),
        sa.Column("url_comprobante", sa.Text(), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "estado IN ('DECLARADO','OBSERVADO','ACEPTADO')",
            name="ck_contrib_estado",
        ),
        sa.UniqueConstraint("patient_id", "periodo", name="uq_contrib_patient_periodo"),
    )
    op.create_index(
        "idx_mc_periodo", "monthly_contributions", ["periodo"]
    )
    op.create_index(
        "idx_mc_patient_periodo", "monthly_contributions", ["patient_id", "periodo"]
    )

    op.create_table(
        "donations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tipo", sa.String(length=16), nullable=False),
        sa.Column("nombre_generico", sa.String(length=160)),
        sa.Column("marca", sa.String(length=120)),
        sa.Column("nombre_comercial", sa.String(length=160)),
        sa.Column("presentacion", sa.String(length=120)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint(
            "tipo IN ('MED','INSULINA','INSUMO')", name="ck_donations_tipo"
        ),
    )

    op.create_table(
        "donation_lots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("donation_id", sa.BigInteger(), nullable=False),
        sa.Column("lote", sa.String(length=80)),
        sa.Column("fecha_venc", sa.Date()),
        sa.Column("cantidad_total", sa.Integer(), nullable=False),
        sa.Column("cantidad_disponible", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["donation_id"], ["donations.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_lots_venc", "donation_lots", ["fecha_venc"])

    op.create_table(
        "donation_allocations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("lot_id", sa.BigInteger(), nullable=False),
        sa.Column("patient_id", sa.BigInteger(), nullable=False),
        sa.Column("cantidad_sugerida", sa.Integer(), nullable=False),
        sa.Column("cantidad_ajustada", sa.Integer()),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("autor_ajuste", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["lot_id"], ["donation_lots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["autor_ajuste"], ["users.id"]),
        sa.CheckConstraint(
            "estado IN ('BORRADOR','CONSOLIDADO')", name="ck_alloc_estado"
        ),
    )
    op.create_index(
        "idx_alloc_patient_estado", "donation_allocations", ["patient_id", "estado"]
    )

    op.create_table(
        "deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("allocation_id", sa.BigInteger(), nullable=False),
        sa.Column("patient_id", sa.BigInteger(), nullable=False),
        sa.Column("fecha_entrega", sa.Date(), nullable=False),
        sa.Column("cantidad_entregada", sa.Integer(), nullable=False),
        sa.Column("url_constancia_pdf", sa.Text()),
        sa.Column("estado", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["allocation_id"], ["donation_allocations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "estado IN ('PENDIENTE_CARGA','CARGADA','VALIDADA')",
            name="ck_delivery_estado",
        ),
    )
    op.create_index(
        "idx_deliv_patient_fecha", "deliveries", ["patient_id", "fecha_entrega"]
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("actor_id", sa.BigInteger()),
        sa.Column("entidad", sa.Text(), nullable=False),
        sa.Column("entidad_id", sa.BigInteger(), nullable=False),
        sa.Column("accion", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
    )
    op.create_index("idx_audit_entidad", "audit_logs", ["entidad", "entidad_id"])
    op.create_index("idx_audit_actor", "audit_logs", ["actor_id", "created_at"])

    # Seed mínimos
    patient_states_table = sa.table(
        "patient_states",
        sa.column("code", sa.Text),
    )
    op.bulk_insert(
        patient_states_table,
        [
            {"code": "ACTIVO"},
            {"code": "INACTIVO"},
            {"code": "PENDIENTE_DOC"},
            {"code": "PENDIENTE_APORTE"},
        ],
    )

    comp_types_table = sa.table(
        "complication_types",
        sa.column("code", sa.Text),
    )
    op.bulk_insert(
        comp_types_table,
        [
            {"code": "RETINOPATIA"},
            {"code": "NEFROPATIA"},
            {"code": "NEUROPATIA"},
            {"code": "PIE_DIABETICO"},
            {"code": "CARDIOVASCULAR"},
            {"code": "OTRAS"},
        ],
    )


def downgrade():
    op.drop_index("idx_audit_actor", table_name="audit_logs")
    op.drop_index("idx_audit_entidad", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("idx_deliv_patient_fecha", table_name="deliveries")
    op.drop_table("deliveries")

    op.drop_index("idx_alloc_patient_estado", table_name="donation_allocations")
    op.drop_table("donation_allocations")

    op.drop_index("idx_lots_venc", table_name="donation_lots")
    op.drop_table("donation_lots")

    op.drop_table("donations")

    op.drop_index("idx_mc_patient_periodo", table_name="monthly_contributions")
    op.drop_index("idx_mc_periodo", table_name="monthly_contributions")
    op.drop_table("monthly_contributions")

    op.drop_table("voluntary_pledges")

    op.drop_table("patient_documents")

    op.drop_table("patient_treatments")

    op.drop_table("patient_complications")

    op.drop_table("patient_medical")

    op.drop_table("tutors")

    op.drop_index("idx_patients_depto_muni", table_name="patients")
    op.drop_index("idx_patients_estado", table_name="patients")
    op.drop_table("patients")

    op.drop_table("users")

    op.drop_table("complication_types")
    op.drop_table("patient_states")

    op.execute("DROP EXTENSION IF EXISTS citext")
