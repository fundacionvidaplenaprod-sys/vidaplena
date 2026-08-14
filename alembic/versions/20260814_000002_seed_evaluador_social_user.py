"""seed EVALUADOR_SOCIAL user (evaluadorsocial@vidaplena.org)

Crea el usuario que recibirá/gestionará las evaluaciones socioeconómicas
enviadas por los beneficiarios. Idempotente: si el email ya existe, no hace
nada (permite reaplicar en distintos entornos sin duplicar ni fallar).

Revision ID: 20260814_000002
Revises: 20260814_000001
Create Date: 2026-08-14

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260814_000002"
down_revision = "20260814_000001"
branch_labels = None
depends_on = None

EVALUADOR_EMAIL = "evaluadorsocial@vidaplena.org"
EVALUADOR_PASSWORD = "Plen@Vid@26"


def upgrade():
    # Import diferido: el hash se calcula con el mismo algoritmo que usa el
    # endpoint POST /users/ (app/core/security.hash_password).
    from app.core.security import hash_password

    bind = op.get_bind()

    existing = bind.execute(
        sa.text("SELECT id FROM users WHERE email = :email"),
        {"email": EVALUADOR_EMAIL},
    ).first()
    if existing:
        return

    users_table = sa.table(
        "users",
        sa.column("email", sa.String),
        sa.column("password_hash", sa.Text),
        sa.column("role", sa.String),
        sa.column("estado", sa.String),
    )
    bind.execute(
        users_table.insert().values(
            email=EVALUADOR_EMAIL,
            password_hash=hash_password(EVALUADOR_PASSWORD),
            role="EVALUADOR_SOCIAL",
            estado="ACTIVO",
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM users WHERE email = :email"), {"email": EVALUADOR_EMAIL})
