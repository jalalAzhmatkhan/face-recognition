"""Engine/session factory.

`database_url` comes from `Settings` (env var `DATABASE_URL`, e.g.
`postgresql+psycopg://user:pass@localhost:5432/frac`) — never hardcoded here.
Engine creation is lazy (`get_engine`/`get_sessionmaker` are `lru_cache`d) so importing
this module never requires a reachable database (needed for import-level tests, alembic
`--sql` dry-runs, etc.).
"""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured. Set it via environment/.env before "
            "creating a database engine."
        )
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped `Session`."""
    session_factory = get_sessionmaker()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
