"""Registro Asistido por Situación Excepcional

Tres tablas nuevas, independientes de `patients`: la persona asistida no tiene usuario, no aporta y no
entra en los reportes de aportes ni de morosos (gratuidad absoluta, Art. 17 del reglamento). Todos los
datos personales son opcionales.

Revision ID: 20261024_000001
Revises: 20261023_000001
Create Date: 2026-10-24

"""
from alembic import op
import sqlalchemy as sa

revision = "20261024_000001"
down_revision = "20261023_000001"
branch_labels = None
depends_on = None


def _in_list(column, values):
    return f"{column} IS NULL OR {column} IN (" + ",".join(f"'{v}'" for v in values) + ")"


ENTIDAD_TIPOS = (
    "CENTRO_ACOGIDA", "RECINTO_PENITENCIARIO", "CENTRO_REINTEGRACION", "HOGAR_ALBERGUE",
    "ASILO_LARGA_ESTANCIA", "CENTRO_ESPECIALIZADO", "CASA_REFUGIO", "COMUNIDAD", "SITUACION_CALLE", "OTRO",
)
VINCULOS = (
    "PERSONAL_SALUD", "TRABAJADOR_SOCIAL", "EDUCADOR", "DEFENSOR", "VOLUNTARIO", "FAMILIAR", "ALLEGADO", "OTRO",
)
RANGOS_EDAD = ("0-11", "12-17", "18-59", "60+")
ESTADOS = ("ACTIVO", "DENEGADO", "CESADO")
CESE_CAUSAS = ("FALLECIMIENTO", "RENUNCIA", "SIN_NECESIDAD", "TRASLADO_REGIMEN_ORDINARIO", "FALTA_GRAVE")
RECEPTOR_TIPOS = ("PERSONA", "PERSONA_REFERENTE", "PERSONAL_SALUD", "OTRO_MEDIO")
CONSTANCIA_TIPOS = ("FIRMA", "HUELLA", "CONFIRMACION", "TESTIMONIO_PERSONAL", "NINGUNA")


def upgrade():
    op.create_table(
        "assisted_registrations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("codigo", sa.String(20), nullable=True, unique=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVO"),
        sa.Column("nombre", sa.String(160), nullable=True),
        sa.Column("rango_edad", sa.String(10), nullable=True),
        sa.Column("edad_aproximada", sa.Integer(), nullable=True),
        sa.Column("depto", sa.String(80), nullable=True),
        sa.Column("ciudad_localidad", sa.String(120), nullable=True),
        sa.Column("entidad_nombre", sa.String(200), nullable=True),
        sa.Column("entidad_tipo", sa.String(30), nullable=True),
        sa.Column("referente_nombre", sa.String(160), nullable=True),
        sa.Column("referente_vinculo", sa.String(30), nullable=True),
        sa.Column("referente_contacto", sa.String(160), nullable=True),
        sa.Column("insumos_requeridos", sa.String(500), nullable=True),
        sa.Column("urgente", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("buen_uso_comunicado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("buen_uso_comunicado_por_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("motivo_denegacion", sa.Text(), nullable=True),
        sa.Column("cese_causa", sa.String(30), nullable=True),
        sa.Column("cese_detalle", sa.Text(), nullable=True),
        sa.Column("cese_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("patient_id", sa.BigInteger(), sa.ForeignKey("patients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ultima_revision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultima_revision_por_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("registrado_por_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(_in_list("entidad_tipo", ENTIDAD_TIPOS), name="ck_assisted_entidad_tipo"),
        sa.CheckConstraint(_in_list("referente_vinculo", VINCULOS), name="ck_assisted_referente_vinculo"),
        sa.CheckConstraint(_in_list("rango_edad", RANGOS_EDAD), name="ck_assisted_rango_edad"),
        sa.CheckConstraint(_in_list("cese_causa", CESE_CAUSAS), name="ck_assisted_cese_causa"),
        sa.CheckConstraint("estado IN (" + ",".join(f"'{v}'" for v in ESTADOS) + ")", name="ck_assisted_estado"),
    )
    op.create_index("ix_assisted_registrations_estado", "assisted_registrations", ["estado"])

    op.create_table(
        "assisted_treatments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("registration_id", sa.BigInteger(), sa.ForeignKey("assisted_registrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("insulina", sa.String(120), nullable=False),
        sa.Column("dosis_diaria", sa.Float(), nullable=True),
    )
    op.create_index("ix_assisted_treatments_registration_id", "assisted_treatments", ["registration_id"])

    op.create_table(
        "assisted_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("registration_id", sa.BigInteger(), sa.ForeignKey("assisted_registrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False, server_default=sa.func.current_date()),
        sa.Column("insumo", sa.String(160), nullable=False),
        sa.Column("cantidad", sa.String(60), nullable=False),
        sa.Column("receptor_tipo", sa.String(30), nullable=True),
        sa.Column("receptor_nombre", sa.String(160), nullable=True),
        sa.Column("constancia_tipo", sa.String(30), nullable=True),
        sa.Column("entregado_por_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(_in_list("receptor_tipo", RECEPTOR_TIPOS), name="ck_assisted_receptor_tipo"),
        sa.CheckConstraint(_in_list("constancia_tipo", CONSTANCIA_TIPOS), name="ck_assisted_constancia_tipo"),
    )
    op.create_index("ix_assisted_deliveries_registration_id", "assisted_deliveries", ["registration_id"])


def downgrade():
    op.drop_table("assisted_deliveries")
    op.drop_table("assisted_treatments")
    op.drop_table("assisted_registrations")
