"""Unit tests for `app/services/recognition_config_service.py`'s 3-layer
resolution contract (EC-BE-04, TSD-edge-cases.md D-4.2/D-10, OQ-6) and its
CRUD helper functions, exercised against a minimal in-memory fake repository
(no DB needed) — mirrors the level of testing
tests/test_access_policies_router.py's fakes give the router, but goes one
layer deeper since `resolve_recognition_config` has no HTTP endpoint of its
own (it's a contract for EC-IN-04/EC-TR-08, not this task's API surface).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.models.enums import RecognitionConfigScope
from app.models.recognition_config import RecognitionConfig
from app.services import recognition_config_service as svc


class FakeAuditLogRepository:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, actor: str, action: str, entity: str, payload=None):
        entry = {"actor": actor, "action": action, "entity": entity, "payload": payload}
        self.entries.append(entry)
        return entry


class FakeRecognitionConfigRepository:
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, RecognitionConfig] = {}

    def get(self, config_id):
        return self._by_id.get(config_id)

    def get_by_key(self, *, scope, scope_ref, mode):
        for config in self._by_id.values():
            if config.scope == scope and config.scope_ref == scope_ref and config.mode == mode:
                return config
        return None

    def list(self, *, scope=None, scope_ref=None, mode=None, limit=100, offset=0):
        items = list(self._by_id.values())
        if scope is not None:
            items = [c for c in items if c.scope == scope]
        if scope_ref is not None:
            items = [c for c in items if c.scope_ref == scope_ref]
        if mode is not None:
            items = [c for c in items if c.mode == mode]
        return items[offset : offset + limit]

    def count(self, **kwargs):
        return len(self.list(**kwargs, limit=10**9, offset=0))

    def create(self, config):
        config.id = config.id or uuid.uuid4()
        now = datetime.now(UTC)
        config.created_at = now
        config.updated_at = now
        self._by_id[config.id] = config
        return config

    def update(self, config):
        config.updated_at = datetime.now(UTC)
        self._by_id[config.id] = config
        return config

    def delete(self, config):
        self._by_id.pop(config.id, None)


@pytest.fixture
def repo() -> FakeRecognitionConfigRepository:
    return FakeRecognitionConfigRepository()


@pytest.fixture
def audit_repo() -> FakeAuditLogRepository:
    return FakeAuditLogRepository()


ARTEFACT_DEFAULTS = {
    "similarity_threshold": 0.42,
    "margin": 0.05,
    "liveness_threshold": 0.6,
    "min_frames": 3,
}


def _candidates(user_id: uuid.UUID | None, device_class: str | None):
    candidates: list[tuple[RecognitionConfigScope, str | None]] = []
    if user_id is not None:
        candidates.append((RecognitionConfigScope.USER, str(user_id)))
    if device_class is not None:
        candidates.append((RecognitionConfigScope.DEVICE_CLASS, device_class))
    candidates.append((RecognitionConfigScope.GLOBAL, None))
    return candidates


# --- create/update/delete + audit -------------------------------------------


def test_create_config_writes_audit_entry(
    repo: FakeRecognitionConfigRepository, audit_repo: FakeAuditLogRepository
) -> None:
    staff_id = uuid.uuid4()
    config = svc.create_config(
        repo,
        audit_repo,
        scope=RecognitionConfigScope.GLOBAL,
        scope_ref=None,
        mode="normal",
        similarity_threshold=0.5,
        margin=None,
        liveness_threshold=None,
        min_frames=None,
        created_by_staff_id=staff_id,
        actor=str(staff_id),
    )
    assert config.similarity_threshold == 0.5
    assert len(audit_repo.entries) == 1
    assert audit_repo.entries[0]["action"] == "recognition_config.create"


def test_create_config_duplicate_key_raises(
    repo: FakeRecognitionConfigRepository, audit_repo: FakeAuditLogRepository
) -> None:
    staff_id = uuid.uuid4()
    kwargs = dict(
        scope=RecognitionConfigScope.DEVICE_CLASS,
        scope_ref="door_entry",
        mode="masked",
        similarity_threshold=0.5,
        margin=None,
        liveness_threshold=None,
        min_frames=None,
        created_by_staff_id=staff_id,
        actor=str(staff_id),
    )
    svc.create_config(repo, audit_repo, **kwargs)
    with pytest.raises(svc.DuplicateConfigError):
        svc.create_config(repo, audit_repo, **kwargs)


def test_update_config_clears_field_to_null(
    repo: FakeRecognitionConfigRepository, audit_repo: FakeAuditLogRepository
) -> None:
    staff_id = uuid.uuid4()
    config = svc.create_config(
        repo,
        audit_repo,
        scope=RecognitionConfigScope.GLOBAL,
        scope_ref=None,
        mode="normal",
        similarity_threshold=0.5,
        margin=0.05,
        liveness_threshold=None,
        min_frames=None,
        created_by_staff_id=staff_id,
        actor=str(staff_id),
    )
    updated = svc.update_config(
        repo, audit_repo, config_id=config.id, updates={"margin": None}, actor=str(staff_id)
    )
    assert updated.margin is None
    assert updated.similarity_threshold == 0.5  # untouched field unaffected
    assert any(e["action"] == "recognition_config.update" for e in audit_repo.entries)


def test_update_config_not_found_raises(
    repo: FakeRecognitionConfigRepository, audit_repo: FakeAuditLogRepository
) -> None:
    with pytest.raises(svc.ConfigNotFoundError):
        svc.update_config(
            repo, audit_repo, config_id=uuid.uuid4(), updates={"margin": 0.1}, actor="x"
        )


def test_delete_config_writes_audit_entry_and_removes_row(
    repo: FakeRecognitionConfigRepository, audit_repo: FakeAuditLogRepository
) -> None:
    staff_id = uuid.uuid4()
    config = svc.create_config(
        repo,
        audit_repo,
        scope=RecognitionConfigScope.GLOBAL,
        scope_ref=None,
        mode="normal",
        similarity_threshold=0.5,
        margin=None,
        liveness_threshold=None,
        min_frames=None,
        created_by_staff_id=staff_id,
        actor=str(staff_id),
    )
    svc.delete_config(repo, audit_repo, config_id=config.id, actor=str(staff_id))
    assert repo.get(config.id) is None
    assert any(e["action"] == "recognition_config.delete" for e in audit_repo.entries)


def test_delete_config_not_found_raises(
    repo: FakeRecognitionConfigRepository, audit_repo: FakeAuditLogRepository
) -> None:
    with pytest.raises(svc.ConfigNotFoundError):
        svc.delete_config(repo, audit_repo, config_id=uuid.uuid4(), actor="x")


# --- resolve_recognition_config: the 3-layer contract -----------------------


def test_resolve_falls_through_entirely_to_artefact_defaults_when_no_override(
    repo: FakeRecognitionConfigRepository,
) -> None:
    """No recognition_configs row at all for this mode -> every field comes
    from artefact_defaults, matched_scope is None."""
    result = svc.resolve_recognition_config(
        repo,
        _candidates(uuid.uuid4(), "door_entry"),
        mode="normal",
        artefact_defaults=ARTEFACT_DEFAULTS,
    )
    assert result.as_dict()["similarity_threshold"] == ARTEFACT_DEFAULTS["similarity_threshold"]
    assert result.min_frames == ARTEFACT_DEFAULTS["min_frames"]
    assert result.matched_scope is None
    assert result.matched_config_id is None


def test_resolve_uses_device_class_override_when_present(
    repo: FakeRecognitionConfigRepository, audit_repo: FakeAuditLogRepository
) -> None:
    """A DEVICE_CLASS override exists (only similarity_threshold set) -> it
    wins over the artefact default for that field; other fields fall
    through to the artefact default since this ONE matched row left them
    NULL (not merged with a less-specific GLOBAL row)."""
    staff_id = uuid.uuid4()
    svc.create_config(
        repo,
        audit_repo,
        scope=RecognitionConfigScope.DEVICE_CLASS,
        scope_ref="attendance",
        mode="masked",
        similarity_threshold=0.35,
        margin=None,
        liveness_threshold=None,
        min_frames=None,
        created_by_staff_id=staff_id,
        actor=str(staff_id),
    )
    # A GLOBAL row for the same mode also exists, but must NOT be consulted
    # since the more-specific DEVICE_CLASS row already matched.
    svc.create_config(
        repo,
        audit_repo,
        scope=RecognitionConfigScope.GLOBAL,
        scope_ref=None,
        mode="masked",
        similarity_threshold=None,
        margin=0.99,
        liveness_threshold=None,
        min_frames=None,
        created_by_staff_id=staff_id,
        actor=str(staff_id),
    )

    result = svc.resolve_recognition_config(
        repo,
        _candidates(None, "attendance"),
        mode="masked",
        artefact_defaults=ARTEFACT_DEFAULTS,
    )
    assert result.similarity_threshold == 0.35
    # margin falls through to artefact default, NOT the GLOBAL row's 0.99.
    assert result.margin == ARTEFACT_DEFAULTS["margin"]
    assert result.matched_scope == RecognitionConfigScope.DEVICE_CLASS
    assert result.matched_scope_ref == "attendance"


def test_resolve_prefers_user_scope_over_device_class_and_global(
    repo: FakeRecognitionConfigRepository, audit_repo: FakeAuditLogRepository
) -> None:
    staff_id = uuid.uuid4()
    user_id = uuid.uuid4()
    for scope, scope_ref, similarity_threshold in (
        (RecognitionConfigScope.GLOBAL, None, 0.5),
        (RecognitionConfigScope.DEVICE_CLASS, "door_entry", 0.45),
        (RecognitionConfigScope.USER, str(user_id), 0.9),
    ):
        svc.create_config(
            repo,
            audit_repo,
            scope=scope,
            scope_ref=scope_ref,
            mode="normal",
            similarity_threshold=similarity_threshold,
            margin=None,
            liveness_threshold=None,
            min_frames=None,
            created_by_staff_id=staff_id,
            actor=str(staff_id),
        )

    # Deliberately pass candidates in a DIFFERENT order than priority
    # (global first) — resolution must still pick USER.
    candidates = [
        (RecognitionConfigScope.GLOBAL, None),
        (RecognitionConfigScope.DEVICE_CLASS, "door_entry"),
        (RecognitionConfigScope.USER, str(user_id)),
    ]
    result = svc.resolve_recognition_config(repo, candidates, mode="normal")
    assert result.similarity_threshold == 0.9
    assert result.matched_scope == RecognitionConfigScope.USER


def test_resolve_falls_back_to_global_when_no_user_or_device_class_override(
    repo: FakeRecognitionConfigRepository, audit_repo: FakeAuditLogRepository
) -> None:
    staff_id = uuid.uuid4()
    svc.create_config(
        repo,
        audit_repo,
        scope=RecognitionConfigScope.GLOBAL,
        scope_ref=None,
        mode="dark",
        similarity_threshold=0.2,
        margin=None,
        liveness_threshold=None,
        min_frames=None,
        created_by_staff_id=staff_id,
        actor=str(staff_id),
    )
    result = svc.resolve_recognition_config(
        repo,
        _candidates(uuid.uuid4(), "door_entry"),
        mode="dark",
        artefact_defaults=ARTEFACT_DEFAULTS,
    )
    assert result.similarity_threshold == 0.2
    assert result.matched_scope == RecognitionConfigScope.GLOBAL


def test_resolve_with_no_artefact_defaults_returns_none_for_unmatched_fields(
    repo: FakeRecognitionConfigRepository,
) -> None:
    """Caller may omit artefact_defaults entirely (e.g. unknown artefact) —
    unmatched fields resolve to None rather than raising."""
    result = svc.resolve_recognition_config(
        repo, _candidates(None, None), mode="normal"
    )
    assert result.similarity_threshold is None
    assert result.margin is None
    assert result.liveness_threshold is None
    assert result.min_frames is None
    assert result.matched_scope is None
