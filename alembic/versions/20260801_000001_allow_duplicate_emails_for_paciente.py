"""Allow duplicate emails for PACIENTE accounts (tutors sharing email for minor children)

Revision ID: 20260801_000001
Revises: 20260730_000002
Create Date: 2026-08-01

Changes:
- Drop UNIQUE constraint on users.email to allow tutors to reuse their email
  when registering their minor children as separate PACIENTE accounts.
  Account uniqueness is now guaranteed by the combination of email + password.
- Drop NOT NULL on patients.ci, patients.ap_paterno, patients.fecha_nac
  (already applied manually in production, formalizing here for consistency).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "20260801_000001"
down_revision = "20260730_000002"
branch_labels = None
depends_on = None


def upgrade():
    # Remove UNIQUE constraint from users.email.
    # Use IF EXISTS so the migration is idempotent (safe if already applied manually).
    op.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key;"))

    # Formally allow NULLs in patients fields relaxed for CSV import.
    # IF NOT NULL check prevents error if already nullable.
    op.execute(text("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='patients' AND column_name='ci' AND is_nullable='NO'
            ) THEN
                ALTER TABLE patients ALTER COLUMN ci DROP NOT NULL;
            END IF;
        END $$;
    """))
    op.execute(text("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='patients' AND column_name='ap_paterno' AND is_nullable='NO'
            ) THEN
                ALTER TABLE patients ALTER COLUMN ap_paterno DROP NOT NULL;
            END IF;
        END $$;
    """))
    op.execute(text("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='patients' AND column_name='fecha_nac' AND is_nullable='NO'
            ) THEN
                ALTER TABLE patients ALTER COLUMN fecha_nac DROP NOT NULL;
            END IF;
        END $$;
    """))


def downgrade():
    # Restore NOT NULL (WARNING: will fail if there are NULL values in the column)
    op.alter_column("patients", "fecha_nac",
                    existing_type=sa.Date(),
                    nullable=False)
    op.alter_column("patients", "ap_paterno",
                    existing_type=sa.String(length=80),
                    nullable=False)
    op.alter_column("patients", "ci",
                    existing_type=sa.String(length=32),
                    nullable=False)

    # Restore UNIQUE on users.email (WARNING: will fail if duplicates exist)
    op.create_unique_constraint("users_email_key", "users", ["email"])
