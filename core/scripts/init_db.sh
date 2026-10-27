#!/usr/bin/env bash
# Tottie — create the local `tottie` Postgres database and apply the schema.
# Requires a running Postgres with the pgvector extension available.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCHEMA="$HERE/../app/schema.sql"

DB_NAME="${TOTTIE_DB_NAME:-tottie}"
PG_USER="${PGUSER:-$(whoami)}"
PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"

echo ">> creating database '$DB_NAME' (if absent) on $PGHOST:$PGPORT as $PG_USER"
psql -h "$PGHOST" -p "$PGPORT" -U "$PG_USER" -d postgres -tc \
  "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 || \
  createdb -h "$PGHOST" -p "$PGPORT" -U "$PG_USER" "$DB_NAME"

echo ">> applying schema: $SCHEMA"
psql -h "$PGHOST" -p "$PGPORT" -U "$PG_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$SCHEMA"

echo ">> done. TOTTIE_DB_URL=postgresql://$PG_USER@$PGHOST:$PGPORT/$DB_NAME"
