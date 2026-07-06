#!/bin/sh
set -e

echo "[entrypoint-sync-worker] Running database migrations..."
alembic upgrade head

echo "[entrypoint-sync-worker] Starting Telegram sync worker..."
exec python -m app.workers.sync_worker
