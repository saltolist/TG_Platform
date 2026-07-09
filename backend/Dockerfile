FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the default local embedding model into the image so RAG works offline
# after container restarts (fastembed otherwise downloads into ephemeral /tmp).
RUN mkdir -p /app/.cache/fastembed && \
    python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

COPY alembic.ini .
COPY alembic ./alembic
COPY fixtures ./fixtures
COPY app ./app
COPY scripts/entrypoint.sh ./scripts/entrypoint.sh
COPY scripts/entrypoint-celery.sh ./scripts/entrypoint-celery.sh
COPY scripts/entrypoint-sync-worker.sh ./scripts/entrypoint-sync-worker.sh
COPY scripts/warmup_embeddings.py ./scripts/warmup_embeddings.py
RUN chmod +x ./scripts/entrypoint.sh ./scripts/entrypoint-celery.sh ./scripts/entrypoint-sync-worker.sh

EXPOSE 8000

ENTRYPOINT ["./scripts/entrypoint.sh"]
