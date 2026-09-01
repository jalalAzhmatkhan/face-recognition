"""Basic CRUD tests for `app/repositories/identity_similarity_flags.py`
(EC-BE-04, TSD-edge-cases.md D-4.4).

No HTTP endpoint exists for this table in EC-BE-04 (see
app/models/identity_similarity_flag.py's module docstring — it is written by
a later ai-training pipeline task, not staff via the API), so this module
tests the repository's create/list/list_for_user primitives directly against
a real SQLite-backed session standing in for the ORM layer's behaviour
(unique-key-free CRUD, ordering, and the both-sides `list_for_user` lookup)
without needing a live Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.identity_similarity_flag import IdentitySimilarityFlag
from app.models.user import User
from app.repositories.identity_similarity_flags import IdentitySimilarityFlagRepository


@pytest.fixture
def session() -> Session:
    # SQLite in-memory: sufficient for this table (no jsonb/vector/native
    # pg-enum columns involved) — same lightweight-DB testing style as
    # tests/test_enrollment_state_machine.py.
    engine = create_engine("sqlite:///:memory:")
    tables = [
        User.__table__,
        IdentitySimilarityFlag.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine) as session:
        yield session


def _make_user(session: Session) -> User:
    user = User(id=uuid.uuid4(), external_ref=f"EMP-{uuid.uuid4().hex[:6]}", full_name="Test")
    session.add(user)
    session.commit()
    return user


def test_create_and_list(session: Session) -> None:
    repo = IdentitySimilarityFlagRepository(session)
    user_a = _make_user(session)
    user_b = _make_user(session)

    flag = repo.create(
        IdentitySimilarityFlag(user_a_id=user_a.id, user_b_id=user_b.id, score=0.91)
    )
    assert flag.id is not None
    assert flag.flagged_at is not None

    items = repo.list()
    assert len(items) == 1
    assert items[0].score == 0.91


def test_list_orders_most_recent_first(session: Session) -> None:
    repo = IdentitySimilarityFlagRepository(session)
    user_a = _make_user(session)
    user_b = _make_user(session)
    user_c = _make_user(session)

    now = datetime.now(UTC)
    repo.create(
        IdentitySimilarityFlag(
            user_a_id=user_a.id, user_b_id=user_b.id, score=0.8, flagged_at=now - timedelta(days=1)
        )
    )
    repo.create(
        IdentitySimilarityFlag(user_a_id=user_a.id, user_b_id=user_c.id, score=0.85, flagged_at=now)
    )

    items = repo.list()
    assert [round(i.score, 2) for i in items] == [0.85, 0.8]


def test_list_for_user_matches_either_side_of_the_pair(session: Session) -> None:
    repo = IdentitySimilarityFlagRepository(session)
    user_a = _make_user(session)
    user_b = _make_user(session)
    user_c = _make_user(session)

    repo.create(IdentitySimilarityFlag(user_a_id=user_a.id, user_b_id=user_b.id, score=0.9))
    repo.create(IdentitySimilarityFlag(user_a_id=user_c.id, user_b_id=user_a.id, score=0.88))
    repo.create(IdentitySimilarityFlag(user_a_id=user_b.id, user_b_id=user_c.id, score=0.2))

    flags_for_a = repo.list_for_user(user_a.id)
    assert len(flags_for_a) == 2

    flags_for_c = repo.list_for_user(user_c.id)
    assert len(flags_for_c) == 2
    assert all(user_c.id in (f.user_a_id, f.user_b_id) for f in flags_for_c)


def test_get_returns_none_for_unknown_id(session: Session) -> None:
    repo = IdentitySimilarityFlagRepository(session)
    assert repo.get(uuid.uuid4()) is None
