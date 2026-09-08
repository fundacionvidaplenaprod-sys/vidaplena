"""patients: exoneracion del aporte mensual por cargo (Responsable Departamental)

Incentivo previsto por normativa interna: los responsables departamentales no
reciben sueldo, y algunos son ademas beneficiarios. Un SUPER_ADMIN puede
exonerarlos del aporte mensual.

La exoneracion NO reutiliza `exonerado_aporte`: esa columna la reescribe la
evaluacion socioeconomica en cada revision (incluido ponerla en False), asi
que compartirla haria que la proxima reevaluacion borrara la exoneracion en
silencio. Son dos causas distintas y los reportes las distinguen.

`exonerado_cargo_user_id` ata la exoneracion a la cuenta de personal del
responsable. Ese vinculo es lo que permite revocarla automaticamente cuando
deja el cargo, porque la cuenta de staff y la ficha de beneficiario son
entidades separadas (hoy ningun responsable tiene ficha vinculada).

Revision ID: 20260908_000001
Revises: 20260904_000001
Create Date: 2026-09-08

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260908_000001"
down_revision = "20260904_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "patients",
        sa.Column(
            "exonerado_por_cargo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "patients",
        sa.Column("exonerado_cargo_user_id", sa.BigInteger(), nullable=True),
    )
    op.add_column("patients", sa.Column("exonerado_cargo_motivo", sa.Text(), nullable=True))
    op.add_column(
        "patients",
        sa.Column("exonerado_cargo_por", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "patients",
        sa.Column("exonerado_cargo_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_foreign_key(
        "fk_patients_exonerado_cargo_user_id_users",
        "patients",
        "users",
        ["exonerado_cargo_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_patients_exonerado_cargo_por_users",
        "patients",
        "users",
        ["exonerado_cargo_por"],
        ["id"],
        ondelete="SET NULL",
    )

    # Se busca por la cuenta del responsable cada vez que cambia su rol o su
    # estado, para saber si hay que revocar. Sin indice seria un scan de toda
    # la tabla de beneficiarios en cada edicion de usuario.
    op.create_index(
        "ix_patients_exonerado_cargo_user_id",
        "patients",
        ["exonerado_cargo_user_id"],
    )


def downgrade():
    op.drop_index("ix_patients_exonerado_cargo_user_id", table_name="patients")
    op.drop_constraint("fk_patients_exonerado_cargo_por_users", "patients", type_="foreignkey")
    op.drop_constraint("fk_patients_exonerado_cargo_user_id_users", "patients", type_="foreignkey")
    op.drop_column("patients", "exonerado_cargo_at")
    op.drop_column("patients", "exonerado_cargo_por")
    op.drop_column("patients", "exonerado_cargo_motivo")
    op.drop_column("patients", "exonerado_cargo_user_id")
    op.drop_column("patients", "exonerado_por_cargo")
