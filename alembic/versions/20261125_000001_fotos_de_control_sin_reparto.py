"""Las fotos de control del beneficiario ya no dependen de un reparto

Las fotos de sus insulinas ya usadas y de su hemoglobina glucosilada se suben desde el portal cuando quiera, aunque
todavía no haya un reparto consolidado. La tabla `insulin_notice_photos` pasa a `insulin_control_photos`:
- `patient_id` (obligatorio): de quién es la foto (se completa desde el aviso de las que ya había).
- `notice_id` pasa a opcional: el aviso de reparto que tenía vigente al subirla, si tenía uno.
- Sin la restricción de una foto por aviso y tipo: una foto aprobada queda en el historial y la siguiente es otra fila.

Revision ID: 20261125_000001
Revises: 20261124_000005
Create Date: 2026-11-25

"""
from alembic import op
import sqlalchemy as sa

revision = "20261125_000001"
down_revision = "20261124_000005"
branch_labels = None
depends_on = None

T = "insulin_control_photos"


def upgrade():
    op.rename_table("insulin_notice_photos", T)
    op.execute(f"ALTER SEQUENCE insulin_notice_photos_id_seq RENAME TO {T}_id_seq")
    op.execute(f"ALTER INDEX insulin_notice_photos_pkey RENAME TO {T}_pkey")
    op.execute(f"ALTER TABLE {T} RENAME CONSTRAINT ck_insulin_notice_photo_tipo TO ck_insulin_control_photo_tipo")
    op.execute(f"ALTER TABLE {T} RENAME CONSTRAINT ck_insulin_notice_photo_estado TO ck_insulin_control_photo_estado")
    op.execute(
        f"ALTER TABLE {T} RENAME CONSTRAINT insulin_notice_photos_revisada_por_id_fkey TO {T}_revisada_por_id_fkey"
    )
    op.drop_constraint("uq_insulin_notice_photo", T, type_="unique")

    op.add_column(T, sa.Column("patient_id", sa.BigInteger(), nullable=True))
    op.execute(
        f"UPDATE {T} f SET patient_id = n.patient_id FROM insulin_distribution_notices n WHERE n.id = f.notice_id"
    )
    op.alter_column(T, "patient_id", nullable=False)
    op.create_foreign_key(f"{T}_patient_id_fkey", T, "patients", ["patient_id"], ["id"], ondelete="CASCADE")
    op.create_index(f"ix_{T}_patient_id", T, ["patient_id"])

    op.drop_constraint("insulin_notice_photos_notice_id_fkey", T, type_="foreignkey")
    op.alter_column(T, "notice_id", nullable=True)
    op.create_foreign_key(
        f"{T}_notice_id_fkey", T, "insulin_distribution_notices", ["notice_id"], ["id"], ondelete="SET NULL"
    )


def downgrade():
    # El esquema anterior admite una foto por aviso y tipo: las subidas sin aviso y las del historial no caben y se
    # descartan (queda la más reciente de cada aviso y tipo).
    op.execute(f"DELETE FROM {T} WHERE notice_id IS NULL")
    op.execute(
        f"DELETE FROM {T} f USING {T} g WHERE f.notice_id = g.notice_id AND f.tipo = g.tipo "
        "AND (f.subida_at, f.id) < (g.subida_at, g.id)"
    )
    op.drop_constraint(f"{T}_notice_id_fkey", T, type_="foreignkey")
    op.alter_column(T, "notice_id", nullable=False)
    op.create_foreign_key(
        "insulin_notice_photos_notice_id_fkey", T, "insulin_distribution_notices", ["notice_id"], ["id"],
        ondelete="CASCADE",
    )
    op.drop_index(f"ix_{T}_patient_id", table_name=T)
    op.drop_constraint(f"{T}_patient_id_fkey", T, type_="foreignkey")
    op.drop_column(T, "patient_id")
    op.create_unique_constraint("uq_insulin_notice_photo", T, ["notice_id", "tipo"])
    op.execute(
        f"ALTER TABLE {T} RENAME CONSTRAINT {T}_revisada_por_id_fkey TO insulin_notice_photos_revisada_por_id_fkey"
    )
    op.execute(f"ALTER TABLE {T} RENAME CONSTRAINT ck_insulin_control_photo_estado TO ck_insulin_notice_photo_estado")
    op.execute(f"ALTER TABLE {T} RENAME CONSTRAINT ck_insulin_control_photo_tipo TO ck_insulin_notice_photo_tipo")
    op.execute(f"ALTER INDEX {T}_pkey RENAME TO insulin_notice_photos_pkey")
    op.execute(f"ALTER SEQUENCE {T}_id_seq RENAME TO insulin_notice_photos_id_seq")
    op.rename_table(T, "insulin_notice_photos")
