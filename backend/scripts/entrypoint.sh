#!/bin/sh
set -e

echo "[entrypoint] Running database migrations..."
alembic upgrade head

echo "[entrypoint] Seeding presentation and demo accounts..."
python -m app.db.seed

echo "[entrypoint] Warming up local embedding model..."
python scripts/warmup_embeddings.py || echo "[entrypoint] WARNING: embedding warmup failed; RAG retrieval may be unavailable"

echo "[entrypoint] Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
