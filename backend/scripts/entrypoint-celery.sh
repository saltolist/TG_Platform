#!/bin/sh
set -e

# Migrations + seeding already run by the `backend` API service on startup
# (scripts/entrypoint.sh); this entrypoint only starts a Celery process.
# Usage: entrypoint-celery.sh worker|beat

role="${1:-worker}"

case "$role" in
  worker)
    echo "[entrypoint-celery] Starting Celery worker..."
    exec celery -A app.celery_app worker -l info --concurrency=2
    ;;
  beat)
    echo "[entrypoint-celery] Starting Celery beat..."
    exec celery -A app.celery_app beat -l info
    ;;
  *)
    echo "[entrypoint-celery] Unknown role '$role' (expected: worker|beat)" >&2
    exit 1
    ;;
esac
