"""Raw-SQL Postgres access for the ai-training worker (TR-02/TR-03).

`ai-training` is a separate Python project from `backend/` (own
venv/pyproject) and cannot import `app.repositories.*`/
`app.services.enrollment_state_machine` from it. Instead of duplicating
SQLAlchemy models, this package talks to Postgres directly via `psycopg`
(lazy import — the `ml` extra) using plain SQL against the schema `backend`
already owns (TSD §4). See `ai_training.worker.tasks` for how the pieces
compose and `config.DBSettings` for the DB-role permission caveat.
"""
