"""Celery worker for the ai-training side of enrollment processing
(TR-02 QC + TR-03 embedding extraction). See `celery_app.py` for how this
interoperates with `backend/`'s own Celery app without either project
importing the other.
"""
