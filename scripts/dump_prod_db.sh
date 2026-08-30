#!/usr/bin/env bash
#
# Respaldo de la base de datos de PRODUCCIÓN.
#
# Ejecutar EN EL SERVIDOR (por SSH), desde la carpeta donde está el
# docker-compose.yml. No expone nada por HTTP: usa el pg_dump que ya trae
# el contenedor de Postgres.
#
#   ssh usuario@servidor
#   cd /ruta/al/proyecto
#   bash scripts/dump_prod_db.sh
#
# Genera:  backup_vidaplena_AAAAMMDD_HHMMSS.sql.gz  (en la carpeta actual)
#
# Luego, desde tu máquina local:
#   scp usuario@servidor:/ruta/al/proyecto/backup_vidaplena_*.sql.gz .
#   bash scripts/restore_local_db.sh backup_vidaplena_XXXXXXXX_XXXXXX.sql.gz
#
set -euo pipefail

# Nombre del servicio de Postgres en docker-compose.yml
DB_SERVICE="${DB_SERVICE:-db}"

# Detecta "docker compose" (v2) o "docker-compose" (v1)
if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
else
    echo "ERROR: no se encontró 'docker compose' ni 'docker-compose'." >&2
    exit 1
fi

TS="$(date +%Y%m%d_%H%M%S)"
OUT="backup_vidaplena_${TS}.sql.gz"

echo ">> Volcando la BD del servicio '${DB_SERVICE}' ..."
# POSTGRES_USER / POSTGRES_DB ya están definidas dentro del contenedor.
# --no-owner / --no-privileges: el dump se restaura limpio en local sin
# depender de los roles del servidor.
$DC exec -T "$DB_SERVICE" sh -c \
    'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges --clean --if-exists' \
    | gzip > "$OUT"

SIZE="$(du -h "$OUT" | cut -f1)"
echo ">> Listo: ${OUT} (${SIZE})"
echo ">> Copialo a tu máquina con:  scp <este-servidor>:$(pwd)/${OUT} ."
