-- Runs once on first container init (docker-entrypoint-initdb.d), connected
-- to $POSTGRES_DB (the default `frac` app database).
-- Enables pgvector on the app DB and creates a separate `mlflow` DB (with
-- pgvector too, for consistency) for the MLflow backend store (XC-02).
-- BE-02 owns the real business schema/migrations via alembic on `frac`.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE DATABASE mlflow;

\connect mlflow

CREATE EXTENSION IF NOT EXISTS vector;
