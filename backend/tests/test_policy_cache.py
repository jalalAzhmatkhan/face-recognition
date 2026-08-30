"""Unit tests for app/services/policy_cache.py (BE-10, TSD §2.2, FR-INF-05).

No real Redis/Postgres: a plain in-memory `FakeRedis` (dict-backed) stands
in for the redis-py client, and tiny duck-typed fake repositories stand in
for `UserRepository`/`AccessPolicyRepository` — this module only ever calls
`.get(user_id)` / `.list_for_user(user_id)` on them.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.models.enums import UserStatus
from app.services import policy_cache


class FakeUser:
    def __init__(self, user_id: uuid.UUID, status: UserStatus) -> None:
        self.id = user_id
        self.status = status


class FakePolicy:
    def __init__(
        self,
        *,
        user_id: uuid.UUID | None,
        door_group: str,
        allowed: bool = True,
        valid_from=None,
        valid_to=None,
    ) -> None:
        self.user_id = user_id
        self.door_group = door_group
        self.allowed = allowed
        self.valid_from = valid_from
        self.valid_to = valid_to


class FakeUserRepo:
    def __init__(self, users: list[FakeUser] | None = None) -> None:
        self._by_id = {u.id: u for u in (users or [])}

    def get(self, user_id: uuid.UUID):
        return self._by_id.get(user_id)


class FakePolicyRepo:
    def __init__(self, policies: list[FakePolicy] | None = None) -> None:
        self._policies = list(policies or [])

    def list_for_user(self, user_id: uuid.UUID) -> list[FakePolicy]:
        return [p for p in self._policies if p.user_id == user_id]


class FakeRedis:
    """In-memory stand-in for the redis-py client surface policy_cache uses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.store.get(name)

    def set(self, name: str, value: str, ex: int | None = None) -> bool:
        self.store[name] = value
        return True

    def delete(self, name: str) -> int:
        return 1 if self.store.pop(name, None) is not None else 0


class FailingRedis:
    """Simulates a completely unreachable Redis — every call raises."""

    def get(self, name: str) -> str | None:
        raise ConnectionError("simulated Redis outage")

    def set(self, name: str, value: str, ex: int | None = None) -> bool:
        raise ConnectionError("simulated Redis outage")

    def delete(self, name: str) -> int:
        raise ConnectionError("simulated Redis outage")


# --- build_snapshot ---------------------------------------------------------


def test_build_snapshot_returns_none_for_unknown_user() -> None:
    user_repo = FakeUserRepo([])
    policy_repo = FakePolicyRepo([])
    assert policy_cache.build_snapshot(user_repo, policy_repo, uuid.uuid4()) is None


def test_build_snapshot_includes_only_directly_user_scoped_policies() -> None:
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    user_repo = FakeUserRepo([FakeUser(user_id, UserStatus.ACTIVE)])
    policy_repo = FakePolicyRepo(
        [
            FakePolicy(user_id=user_id, door_group="main-entrance"),
            FakePolicy(user_id=other_user_id, door_group="warehouse"),
            FakePolicy(user_id=None, door_group="group-scoped-ignored"),
        ]
    )

    snapshot = policy_cache.build_snapshot(user_repo, policy_repo, user_id)

    assert snapshot is not None
    assert snapshot.status == UserStatus.ACTIVE
    assert [p.door_group for p in snapshot.policies] == ["main-entrance"]


# --- get_cached_snapshot (pure read, never touches the DB) ------------------


def test_get_cached_snapshot_returns_none_on_miss() -> None:
    redis_client = FakeRedis()
    assert policy_cache.get_cached_snapshot(redis_client, uuid.uuid4()) is None


def test_get_cached_snapshot_returns_none_when_redis_unreachable() -> None:
    """A Redis outage must look exactly like a cache miss to the caller —
    both are fail-secure DENY (FR-INF-05)."""
    redis_client = FailingRedis()
    assert policy_cache.get_cached_snapshot(redis_client, uuid.uuid4()) is None


def test_get_cached_snapshot_returns_none_on_malformed_entry() -> None:
    user_id = uuid.uuid4()
    redis_client = FakeRedis()
    redis_client.store[f"policy_snapshot:{user_id}"] = "not valid json"
    assert policy_cache.get_cached_snapshot(redis_client, user_id) is None


def test_get_and_refresh_round_trip() -> None:
    user_id = uuid.uuid4()
    user_repo = FakeUserRepo([FakeUser(user_id, UserStatus.ACTIVE)])
    policy_repo = FakePolicyRepo(
        [FakePolicy(user_id=user_id, door_group="main-entrance", allowed=True)]
    )
    redis_client = FakeRedis()

    written = policy_cache.refresh_cache(redis_client, user_repo, policy_repo, user_id)
    assert written is not None

    fetched = policy_cache.get_cached_snapshot(redis_client, user_id)
    assert fetched is not None
    assert fetched.status == UserStatus.ACTIVE
    assert fetched.policies[0].door_group == "main-entrance"
    assert fetched.policies[0].allowed is True


def test_refresh_cache_preserves_valid_from_to_through_json_round_trip() -> None:
    user_id = uuid.uuid4()
    now = datetime.now(UTC)
    valid_from = now - timedelta(days=1)
    valid_to = now + timedelta(days=1)
    user_repo = FakeUserRepo([FakeUser(user_id, UserStatus.ACTIVE)])
    policy_repo = FakePolicyRepo(
        [
            FakePolicy(
                user_id=user_id,
                door_group="main-entrance",
                valid_from=valid_from,
                valid_to=valid_to,
            )
        ]
    )
    redis_client = FakeRedis()

    policy_cache.refresh_cache(redis_client, user_repo, policy_repo, user_id)
    fetched = policy_cache.get_cached_snapshot(redis_client, user_id)

    assert fetched is not None
    entry = fetched.policies[0]
    assert entry.valid_from == valid_from
    assert entry.valid_to == valid_to


def test_refresh_cache_deletes_stale_entry_when_user_no_longer_exists() -> None:
    user_id = uuid.uuid4()
    redis_client = FakeRedis()
    redis_client.store[f"policy_snapshot:{user_id}"] = '{"status": "ACTIVE", "policies": []}'
    user_repo = FakeUserRepo([])  # user gone
    policy_repo = FakePolicyRepo([])

    result = policy_cache.refresh_cache(redis_client, user_repo, policy_repo, user_id)

    assert result is None
    assert policy_cache.get_cached_snapshot(redis_client, user_id) is None


def test_refresh_cache_is_best_effort_when_redis_write_fails() -> None:
    """Redis being down must not raise out of refresh_cache — callers
    (policy CRUD, user-status update) must never 500 just because the cache
    couldn't be written."""
    user_id = uuid.uuid4()
    user_repo = FakeUserRepo([FakeUser(user_id, UserStatus.ACTIVE)])
    policy_repo = FakePolicyRepo([FakePolicy(user_id=user_id, door_group="main-entrance")])
    redis_client = FailingRedis()

    snapshot = policy_cache.refresh_cache(redis_client, user_repo, policy_repo, user_id)

    assert snapshot is not None  # DB read still succeeded
    assert snapshot.status == UserStatus.ACTIVE
