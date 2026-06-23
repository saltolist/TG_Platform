#!/bin/sh
# Создаёт тест-базу tg_test и применяет все миграции.
# Запускать один раз перед первым прогоном тестов или после новых миграций.
#
# Использование:
#   cd backend && ./scripts/ensure-test-db.sh
#   TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:port/tg_test ./scripts/ensure-test-db.sh
#
# После этого запускать тесты:
#   TEST_DATABASE_URL=postgresql+asyncpg://tg:tg@localhost:5432/tg_test pytest
set -e

# Директория скрипта → корень backend/
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"

# Ищем python: сначала .test-venv, потом .venv, потом системный python3
if [ -x "$BACKEND_DIR/.test-venv/bin/python" ]; then
    PYTHON="$BACKEND_DIR/.test-venv/bin/python"
elif [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
    PYTHON="$BACKEND_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    echo "[ensure-test-db] ОШИБКА: python не найден. Создайте venv:" >&2
    echo "  cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt" >&2
    exit 1
fi

TEST_DB_URL="${TEST_DATABASE_URL:-postgresql+asyncpg://tg:tg@localhost:5432/tg_test}"

# Извлекаем компоненты подключения из URL для psql
# Формат: postgresql+asyncpg://user:pass@host:port/dbname
_url="${TEST_DB_URL#postgresql+asyncpg://}"
_userpass="${_url%%@*}"
_hostdbname="${_url##*@}"

DB_USER="${_userpass%%:*}"
DB_PASS="${_userpass##*:}"
DB_HOST="${_hostdbname%%:*}"
_portdb="${_hostdbname##*:}"
DB_PORT="${_portdb%%/*}"
DB_NAME="${_portdb##*/}"

echo "[ensure-test-db] Python: $PYTHON"
echo "[ensure-test-db] Проверяем базу: ${DB_NAME} на ${DB_HOST}:${DB_PORT}"

# Создаём базу если не существует
PGPASSWORD="$DB_PASS" psql \
    -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" \
    -d postgres \
    -tc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" \
    | grep -q 1 \
    || PGPASSWORD="$DB_PASS" psql \
        -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" \
        -d postgres \
        -c "CREATE DATABASE \"${DB_NAME}\""

echo "[ensure-test-db] База готова. Применяем миграции..."

cd "$BACKEND_DIR"
DATABASE_URL="$TEST_DB_URL" "$PYTHON" -m alembic upgrade head

echo "[ensure-test-db] Готово. Запускайте тесты:"
echo "  TEST_DATABASE_URL=${TEST_DB_URL} pytest"
