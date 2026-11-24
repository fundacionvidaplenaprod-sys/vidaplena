"""Revisión de las fotos del aviso del reparto por el SUPER_ADMIN

Las fotos del beneficiario (insulinas ya usadas y hemoglobina glucosilada) pasan de columnas en
`insulin_distribution_notices` a su propia tabla `insulin_notice_photos`, porque cada una tiene su ciclo: se sube,
el SUPER_ADMIN la aprueba u observa (con el motivo), y si la observa el beneficiario sube otra.

Las fotos que ya hubiera se conservan y quedan por revisar (PENDIENTE).

Revision ID: 20261124_000005
Revises: 20261124_000004
Create Date: 2026-11-24

"""
from alembic import op
import sqlalchemy as sa

revision = "20261124_000005"
down_revision = "20261124_000004"
branch_labels = None
depends_on = None

TIPOS = ("envases", "hba1c")


def upgrade():
    op.create_table(
        "insulin_notice_photos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "notice_id", sa.BigInteger(),
            sa.ForeignKey("insulin_distribution_notices.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("tipo", sa.String(16), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("subida_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("estado", sa.String(16), nullable=False, server_default="PENDIENTE"),
        sa.Column("observacion", sa.Text(), nullable=True),
        sa.Column("revisada_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revisada_por_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("notice_id", "tipo", name="uq_insulin_notice_photo"),
        sa.CheckConstraint("tipo IN ('envases','hba1c')", name="ck_insulin_notice_photo_tipo"),
        sa.CheckConstraint("estado IN ('PENDIENTE','APROBADA','OBSERVADA')", name="ck_insulin_notice_photo_estado"),
    )
    for tipo in TIPOS:
        op.execute(
            f"""
            INSERT INTO insulin_notice_photos (notice_id, tipo, url, subida_at, estado)
            SELECT id, '{tipo}', foto_{tipo}_url, COALESCE(foto_{tipo}_at, now()), 'PENDIENTE'
            FROM insulin_distribution_notices WHERE foto_{tipo}_url IS NOT NULL
            """
        )
    for tipo in reversed(TIPOS):
        op.drop_column("insulin_distribution_notices", f"foto_{tipo}_at")
        op.drop_column("insulin_distribution_notices", f"foto_{tipo}_url")


def downgrade():
    for tipo in TIPOS:
        op.add_column("insulin_distribution_notices", sa.Column(f"foto_{tipo}_url", sa.Text(), nullable=True))
        op.add_column("insulin_distribution_notices", sa.Column(f"foto_{tipo}_at", sa.DateTime(timezone=True), nullable=True))
        op.execute(
            f"""
            UPDATE insulin_distribution_notices n
            SET foto_{tipo}_url = f.url, foto_{tipo}_at = f.subida_at
            FROM insulin_notice_photos f WHERE f.notice_id = n.id AND f.tipo = '{tipo}'
            """
        )
    op.drop_table("insulin_notice_photos")
