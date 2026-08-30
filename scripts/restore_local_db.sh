#!/usr/bin/env bash
#
# Restaura un respaldo de producción en tu Postgres LOCAL.
#
#   bash scripts/restore_local_db.sh backup_vidaplena_20260830_120000.sql.gz
#
# DESTRUCTIVO: borra y recrea la base local antes de restaurar.
#
# Variables (con sus valores por defecto para este proyecto):
#   PGHOST=localhost  PGPORT=5432  PGUSER=postgres  PGPASSWORD=Bisa.2025
#   LOCAL_DB=vidaplena
#
set -euo pipefail

DUMP="${1:-}"
if [ -z "$DUMP" ] || [ ! -f "$DUMP" ]; then
    echo "Uso: bash scripts/restore_local_db.sh <archivo.sql.gz>" >&2
    exit 1
fi

export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-postgres}"
export PGPASSWORD="${PGPASSWORD:-Bisa.2025}"
LOCAL_DB="${LOCAL_DB:-vidaplena}"

command -v psql >/dev/null 2>&1 || { echo "ERROR: falta 'psql' en el PATH." >&2; exit 1; }

echo ">> Esto ELIMINA la base local '${LOCAL_DB}' en ${PGHOST}:${PGPORT} y la reemplaza."
printf ">> Escribe 'si' para continuar: "
read -r CONFIRM
[ "$CONFIRM" = "si" ] || { echo "Cancelado."; exit 1; }

echo ">> Cerrando conexiones y recreando '${LOCAL_DB}' ..."
psql -d postgres -v ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname = '${LOCAL_DB}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS ${LOCAL_DB};
CREATE DATABASE ${LOCAL_DB};
SQL

echo ">> Restaurando ${DUMP} ..."
gunzip -c "$DUMP" | psql -d "$LOCAL_DB" -v ON_ERROR_STOP=1 --quiet

echo ">> Listo. Base local '${LOCAL_DB}' restaurada desde ${DUMP}."
echo ">> Recomendado antes de probar en local:"
echo "     psql -d ${LOCAL_DB} -f scripts/anonymize_local.sql"
