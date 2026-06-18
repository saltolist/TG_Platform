#!/bin/sh
# Runs once when the postgres volume is first created.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE tg_test'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'tg_test')\gexec
EOSQL
