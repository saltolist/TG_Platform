#!/usr/bin/env bash
# Create an isolated Postgres database for pytest (never wipe dev data in `tg`).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

POSTGRES_USER="${POSTGRES_USER:-tg}"
POSTGRES_DB="${POSTGRES_DB:-tg}"
TEST_DB="${TEST_DATABASE_NAME:-tg_test}"

if ! docker compose ps postgres --status running --quiet 2>/dev/null | grep -q .; then
  echo "[ensure-test-db] Postgres is not running. Start the stack first: ./scripts/docker-up.sh"
  exit 1
fi

echo "[ensure-test-db] Ensuring database '${TEST_DB}' exists..."
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<SQL
SELECT 'CREATE DATABASE ${TEST_DB}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${TEST_DB}')\\gexec
SQL

export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD:-tg}@localhost:5432/${TEST_DB}"
echo "[ensure-test-db] Running migrations on ${TEST_DB}..."
(
  cd "$ROOT/backend"
  alembic upgrade head
)

echo "[ensure-test-db] Ready. pytest uses DATABASE ${TEST_DB} (dev data in ${POSTGRES_DB} stays untouched)."
