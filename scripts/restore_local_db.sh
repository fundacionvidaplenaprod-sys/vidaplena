#!/usr/bin/env bash
#
# Restaura un respaldo de producción en tu Postgres LOCAL.
#
#   bash scripts/restore_local_db.sh backup_vidaplena_20260830_120000.sql.gz
#
# DESTRUCTIVO: borra y recrea la base local antes de restaurar.
#
# La conexión sale de la variable DATABASE_URL (del entorno o del archivo
# .env, que NO está versionado). No hay credenciales en este script.
# Formato esperado:
#   postgresql+asyncpg://usuario:clave@host:puerto/basededatos
#
set -euo pipefail

DUMP="${1:-}"
if [ -z "$DUMP" ] || [ ! -f "$DUMP" ]; then
    echo "Uso: bash scripts/restore_local_db.sh <archivo.sql.gz>" >&2
    exit 1
fi

command -v psql >/dev/null 2>&1 || { echo "ERROR: falta 'psql' en el PATH." >&2; exit 1; }

# --- Obtener DATABASE_URL (entorno tiene prioridad; si no, del .env) ---
if [ -z "${DATABASE_URL:-}" ] && [ -f .env ]; then
    DATABASE_URL="$(grep -E '^\s*DATABASE_URL=' .env | tail -n1 | cut -d= -f2- | tr -d '"'"'"'')"
fi
if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: no encuentro DATABASE_URL (ni en el entorno ni en .env)." >&2
    exit 1
fi

# --- Parsear la URL: //usuario:clave@host:puerto/base ---
URL_NOSCHEME="${DATABASE_URL#*://}"
CREDS="${URL_NOSCHEME%%@*}"          # usuario:clave
HOSTPART="${URL_NOSCHEME#*@}"        # host:puerto/base
export PGUSER="${CREDS%%:*}"
export PGPASSWORD="${CREDS#*:}"
export PGHOST="$(printf '%s' "${HOSTPART%%/*}" | cut -d: -f1)"
export PGPORT="$(printf '%s' "${HOSTPART%%/*}" | cut -d: -f2)"
LOCAL_DB="${HOSTPART#*/}"
LOCAL_DB="${LOCAL_DB%%\?*}"          # descarta ?params si los hubiera
[ -n "$PGPORT" ] && [ "$PGPORT" != "$PGHOST" ] || PGPORT=5432

if [ "$PGHOST" != "localhost" ] && [ "$PGHOST" != "127.0.0.1" ]; then
    echo "ERROR: DATABASE_URL apunta a '$PGHOST', no a localhost. Abortando por seguridad." >&2
    exit 1
fi

echo ">> Destino: ${PGUSER}@${PGHOST}:${PGPORT}/${LOCAL_DB}"
echo ">> Esto ELIMINA la base local '${LOCAL_DB}' y la reemplaza con ${DUMP}."
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
