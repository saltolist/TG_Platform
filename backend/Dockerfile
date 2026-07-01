FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY fixtures ./fixtures
COPY app ./app
COPY scripts/entrypoint.sh ./scripts/entrypoint.sh
COPY scripts/entrypoint-celery.sh ./scripts/entrypoint-celery.sh
RUN chmod +x ./scripts/entrypoint.sh ./scripts/entrypoint-celery.sh

EXPOSE 8000

ENTRYPOINT ["./scripts/entrypoint.sh"]
