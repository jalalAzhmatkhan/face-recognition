"""Celery worker infra (BE-07, NFR-OPS-02).

Sub-modules:
  - `celery_app.py` — the `Celery` application instance (broker/backend =
    `Settings.redis_url`, reused from XC-02/config.py — no separate Redis
    config here).
  - `tasks.py` — task base class (retry + dead-letter semantics) and the
    concrete tasks. `run_enrollment_qc` is a STUB for BE-07; TR-02
    (ai-engineer) replaces its body with the real QC pipeline without
    changing its name/signature.
"""
