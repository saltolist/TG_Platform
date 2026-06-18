#!/usr/bin/env bash
# Start Docker stack in background (safe: Ctrl+C in logs does not stop DB).
# Usage: ./scripts/docker-up.sh [--build]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

docker compose up -d "$@"

echo ""
echo "[docker-up] Сервисы запущены в фоне."
echo "  UI:      http://localhost:3000"
echo "  API:     http://localhost:8000/api/v1"
echo "  Логи:    docker compose logs -f backend"
echo "  Стоп:    docker compose stop   (данные сохраняются)"
echo "  НЕ используйте: docker compose down -v  (удалит аккаунты!)"
