"""Registro Asistido: personas referentes reutilizables y datos complementarios

- Nueva tabla `assisted_referents`: la persona referente (nombre completo, C.I., teléfono y foto
  personal) puede serlo de varios beneficiarios, así que deja de guardarse dentro del registro.
- El vínculo con el beneficiario pasa a ser Familiar / Conocido / Referido por terceros / Amistad.
- Datos complementarios opcionales del beneficiario: municipio, C.I., fecha de nacimiento, tipo de
  diabetes, años con diabetes y complicaciones u otras enfermedades.

Los registros que ya tenían referente se conservan: sus datos pasan a una persona referente nueva
(sin C.I. ni foto, que deberán completarse). Un vínculo anterior sin equivalente queda en blanco.

Revision ID: 20261025_000001
Revises: 20261024_000001
Create Date: 2026-10-25

"""
from alembic import op
import sqlalchemy as sa

revision = "20261025_000001"
down_revision = "20261024_000001"
branch_labels = None
depends_on = None


def _in_list(column, values):
    return f"{column} IS NULL OR {column} IN (" + ",".join(f"'{v}'" for v in values) + ")"


VINCULOS_NUEVOS = ("FAMILIAR", "CONOCIDO", "REFERIDO_POR_TERCEROS", "AMISTAD")
VINCULOS_ANTERIORES = (
    "PERSONAL_SALUD", "TRABAJADOR_SOCIAL", "EDUCADOR", "DEFENSOR", "VOLUNTARIO", "FAMILIAR", "ALLEGADO", "OTRO",
)
TIPOS_DIABETES = ("Tipo 1", "Tipo 2", "Gestacional", "Otra")


def upgrade():
    op.create_table(
        "assisted_referents",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("nombre_completo", sa.String(160), nullable=False),
        sa.Column("ci", sa.String(32), nullable=True),
        sa.Column("telefono", sa.String(40), nullable=True),
        sa.Column("foto_url", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # Una misma C.I. no puede registrarse dos veces como persona referente.
    op.create_index(
        "uq_assisted_referents_ci", "assisted_referents", ["ci"], unique=True, postgresql_where=sa.text("ci IS NOT NULL")
    )

    op.add_column("assisted_registrations", sa.Column("municipio", sa.String(120), nullable=True))
    op.add_column("assisted_registrations", sa.Column("ci", sa.String(32), nullable=True))
    op.add_column("assisted_registrations", sa.Column("fecha_nacimiento", sa.Date(), nullable=True))
    op.add_column("assisted_registrations", sa.Column("tipo_diabetes", sa.String(20), nullable=True))
    op.add_column("assisted_registrations", sa.Column("anios_diabetes", sa.Integer(), nullable=True))
    op.add_column("assisted_registrations", sa.Column("complicaciones_otras", sa.String(500), nullable=True))
    op.add_column(
        "assisted_registrations",
        sa.Column("referente_id", sa.BigInteger(), sa.ForeignKey("assisted_referents.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_assisted_registrations_referente_id", "assisted_registrations", ["referente_id"])
    op.create_check_constraint("ck_assisted_tipo_diabetes", "assisted_registrations", _in_list("tipo_diabetes", TIPOS_DIABETES))

    # Los referentes ya anotados dentro de cada registro pasan a la tabla nueva.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, referente_nombre, referente_contacto FROM assisted_registrations "
            "WHERE referente_nombre IS NOT NULL OR referente_contacto IS NOT NULL"
        )
    ).fetchall()
    for reg_id, nombre, contacto in rows:
        referente_id = bind.execute(
            sa.text(
                "INSERT INTO assisted_referents (nombre_completo, telefono) VALUES (:nombre, :tel) RETURNING id"
            ),
            {"nombre": nombre or "(sin nombre)", "tel": contacto},
        ).scalar()
        bind.execute(
            sa.text("UPDATE assisted_registrations SET referente_id = :rid WHERE id = :id"),
            {"rid": referente_id, "id": reg_id},
        )

    op.drop_constraint("ck_assisted_referente_vinculo", "assisted_registrations", type_="check")
    op.execute(
        "UPDATE assisted_registrations SET referente_vinculo = CASE referente_vinculo "
        "WHEN 'FAMILIAR' THEN 'FAMILIAR' WHEN 'ALLEGADO' THEN 'CONOCIDO' ELSE NULL END"
    )
    op.create_check_constraint(
        "ck_assisted_referente_vinculo", "assisted_registrations", _in_list("referente_vinculo", VINCULOS_NUEVOS)
    )
    op.drop_column("assisted_registrations", "referente_nombre")
    op.drop_column("assisted_registrations", "referente_contacto")


def downgrade():
    op.add_column("assisted_registrations", sa.Column("referente_nombre", sa.String(160), nullable=True))
    op.add_column("assisted_registrations", sa.Column("referente_contacto", sa.String(160), nullable=True))
    op.execute(
        "UPDATE assisted_registrations r SET referente_nombre = f.nombre_completo, referente_contacto = f.telefono "
        "FROM assisted_referents f WHERE r.referente_id = f.id"
    )
    op.drop_constraint("ck_assisted_referente_vinculo", "assisted_registrations", type_="check")
    op.execute(
        "UPDATE assisted_registrations SET referente_vinculo = CASE referente_vinculo "
        "WHEN 'FAMILIAR' THEN 'FAMILIAR' WHEN 'REFERIDO_POR_TERCEROS' THEN 'OTRO' "
        "WHEN 'CONOCIDO' THEN 'ALLEGADO' WHEN 'AMISTAD' THEN 'ALLEGADO' ELSE NULL END"
    )
    op.create_check_constraint(
        "ck_assisted_referente_vinculo", "assisted_registrations", _in_list("referente_vinculo", VINCULOS_ANTERIORES)
    )
    op.drop_constraint("ck_assisted_tipo_diabetes", "assisted_registrations", type_="check")
    op.drop_index("ix_assisted_registrations_referente_id", table_name="assisted_registrations")
    op.drop_column("assisted_registrations", "referente_id")
    for column in ("complicaciones_otras", "anios_diabetes", "tipo_diabetes", "fecha_nacimiento", "ci", "municipio"):
        op.drop_column("assisted_registrations", column)
    op.drop_index("uq_assisted_referents_ci", table_name="assisted_referents")
    op.drop_table("assisted_referents")
