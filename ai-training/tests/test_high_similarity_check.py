"""`run_high_similarity_check_core` (D-4.4, TSD-edge-cases.md D-4.4/REC 13,
EC-TR-04) against a fake DB cursor -- never real Postgres, same convention
as test_gallery_reembed.py / test_worker_task_synthetic_masked.py.
"""

from __future__ import annotations

import json

import pytest

from ai_training.config import Settings
from ai_training.similarity.high_similarity_check import run_high_similarity_check_core


class FakeCursor:
    """In-memory stand-in for `face_embeddings` / `identity_similarity_flags`
    / `recognition_configs` / `staff_accounts` / `audit_logs`, dispatched on
    query prefix (mirrors the FakeCursor idiom already established across
    ai-training's worker tests)."""

    def __init__(
        self,
        *,
        embeddings_by_user: dict[str, list[list[float]]],
        global_threshold: float | None = None,
        admin_staff_id: str | None = "staff-admin-1",
    ) -> None:
        self.embeddings_by_user = embeddings_by_user
        self.global_threshold = global_threshold
        self.admin_staff_id = admin_staff_id
        self.flags: list[tuple[str, str, float]] = []
        self.resolved_pairs: set[frozenset[str]] = set()
        # scope=user overrides: user_id -> (config_id, similarity_threshold)
        self.user_overrides: dict[str, tuple[str, float]] = {}
        self.executed: list[tuple[str, tuple]] = []
        self.audit_entries: list[tuple[str, dict]] = []
        self._fetch_one: tuple | None = None
        self._fetch_all: list[tuple] = []

    def execute(self, query: str, params: tuple = ()) -> None:
        self.executed.append((query, params))

        if query.startswith(
            "SELECT similarity_threshold FROM recognition_configs "
            "WHERE scope = %s AND scope_ref IS NULL"
        ):
            self._fetch_one = (
                (self.global_threshold,) if self.global_threshold is not None else None
            )

        elif query.startswith("SELECT vector FROM face_embeddings") and "user_id = %s" in query:
            model_version, template_kind, user_id = params
            vectors = self.embeddings_by_user.get(user_id, [])
            self._fetch_all = [(v,) for v in vectors]

        elif query.startswith("SELECT user_id, vector FROM face_embeddings"):
            model_version, template_kind, exclude_user_id = params
            rows = []
            for user_id, vectors in self.embeddings_by_user.items():
                if user_id == exclude_user_id:
                    continue
                for v in vectors:
                    rows.append((user_id, v))
            self._fetch_all = rows

        elif query.startswith("SELECT 1 FROM identity_similarity_flags"):
            a, b, b2, a2 = params
            pair = frozenset((a, b))
            is_open = pair not in self.resolved_pairs and pair in self._open_pairs()
            self._fetch_one = (1,) if is_open else None

        elif query.startswith("INSERT INTO identity_similarity_flags"):
            _id, user_a_id, user_b_id, score = params
            self.flags.append((user_a_id, user_b_id, score))
            self._fetch_one = None

        elif query.startswith("SELECT id FROM staff_accounts"):
            self._fetch_one = (self.admin_staff_id,) if self.admin_staff_id else None

        elif query.startswith(
            "SELECT id, similarity_threshold FROM recognition_configs "
            "WHERE scope = %s AND scope_ref = %s"
        ):
            _scope, user_id, _mode = params
            existing = self.user_overrides.get(user_id)
            self._fetch_one = existing if existing else None

        elif query.startswith("UPDATE recognition_configs SET similarity_threshold"):
            new_threshold, config_id = params
            for user_id, (cid, _old) in list(self.user_overrides.items()):
                if cid == config_id:
                    self.user_overrides[user_id] = (cid, new_threshold)
            self._fetch_one = None

        elif query.startswith("INSERT INTO recognition_configs"):
            config_id, _scope, scope_ref, _mode, threshold, _staff_id = params
            self.user_overrides[scope_ref] = (config_id, threshold)
            self._fetch_one = None

        elif query.startswith("INSERT INTO audit_logs"):
            _id, _actor, action, _entity, payload_json = params
            payload = json.loads(payload_json) if payload_json is not None else None
            self.audit_entries.append((action, payload))
            self._fetch_one = None

        else:  # pragma: no cover - not exercised by these tests
            self._fetch_one = None
            self._fetch_all = []

    def _open_pairs(self) -> set[frozenset[str]]:
        return {frozenset((a, b)) for a, b, _score in self.flags}

    def fetchone(self):
        return self._fetch_one

    def fetchall(self):
        return self._fetch_all


def _settings() -> Settings:
    return Settings(_env_file=None)


def _unit(index: int, dim: int = 8) -> list[float]:
    vec = [0.0] * dim
    vec[index % dim] = 1.0
    return vec


def test_highly_similar_pair_is_flagged_and_tau_raised_for_both_users() -> None:
    # user-a's fresh template is (numerically) identical to user-b's
    # existing gallery template -- cosine similarity 1.0, comfortably above
    # tau(0.35) - margin_hs(0.05) = 0.30.
    same_vector = _unit(0)
    cursor = FakeCursor(
        embeddings_by_user={"user-a": [same_vector], "user-b": [same_vector]},
    )

    result = run_high_similarity_check_core(
        cursor, _settings(), user_id="user-a", model_version="adaface-v2"
    )

    assert result.tau == 0.35
    assert result.margin_hs == 0.05
    assert result.threshold_hs == 0.30
    assert len(result.flagged) == 1
    flagged = result.flagged[0]
    assert flagged.other_user_id == "user-b"
    assert flagged.score == 1.0
    assert flagged.new_user_threshold == pytest.approx(0.4)
    assert flagged.new_other_user_threshold == pytest.approx(0.4)

    # identity_similarity_flags: one row, either direction is fine (the
    # repository's own lookup checks both columns).
    assert cursor.flags == [("user-a", "user-b", 1.0)]

    # recognition_configs: BOTH identities got a scope=user override raising
    # tau from 0.35 to 0.4 (tau + margin_hs).
    assert cursor.user_overrides["user-a"][1] == pytest.approx(0.4)
    assert cursor.user_overrides["user-b"][1] == pytest.approx(0.4)

    # Audited: one flag entry + two auto-override entries.
    actions = [action for action, _payload in cursor.audit_entries]
    assert actions.count("identity_similarity.flagged") == 1
    assert actions.count("recognition_config.auto_override") == 2


def test_dissimilar_identities_are_not_flagged() -> None:
    cursor = FakeCursor(
        embeddings_by_user={"user-a": [_unit(0)], "user-b": [_unit(1)]},
    )

    result = run_high_similarity_check_core(
        cursor, _settings(), user_id="user-a", model_version="adaface-v2"
    )

    assert result.flagged == []
    assert cursor.flags == []
    assert cursor.user_overrides == {}
    assert cursor.audit_entries == []


def test_rerunning_for_the_same_open_pair_does_not_duplicate_the_flag() -> None:
    same_vector = _unit(0)
    cursor = FakeCursor(
        embeddings_by_user={"user-a": [same_vector], "user-b": [same_vector]},
    )

    run_high_similarity_check_core(
        cursor, _settings(), user_id="user-a", model_version="adaface-v2"
    )
    assert len(cursor.flags) == 1

    # A second run for the SAME pair (e.g. a re-embed) must not insert a
    # second open flag row.
    run_high_similarity_check_core(
        cursor, _settings(), user_id="user-a", model_version="adaface-v2"
    )
    assert len(cursor.flags) == 1

    flagged_actions = [a for a, _p in cursor.audit_entries if a == "identity_similarity.flagged"]
    assert len(flagged_actions) == 1


def test_missing_admin_staff_account_skips_override_but_still_writes_the_flag() -> None:
    same_vector = _unit(0)
    cursor = FakeCursor(
        embeddings_by_user={"user-a": [same_vector], "user-b": [same_vector]},
        admin_staff_id=None,
    )

    result = run_high_similarity_check_core(
        cursor, _settings(), user_id="user-a", model_version="adaface-v2"
    )

    assert len(result.flagged) == 1
    assert result.flagged[0].new_user_threshold is None
    assert result.flagged[0].new_other_user_threshold is None
    assert cursor.flags == [("user-a", "user-b", 1.0)]
    assert cursor.user_overrides == {}

    actions = [action for action, _payload in cursor.audit_entries]
    assert "identity_similarity.flagged" in actions
    assert "recognition_config.auto_override_skipped" in actions


def test_global_recognition_config_override_replaces_default_tau() -> None:
    same_vector = _unit(0)
    cursor = FakeCursor(
        embeddings_by_user={"user-a": [same_vector], "user-b": [same_vector]},
        global_threshold=0.5,
    )

    result = run_high_similarity_check_core(
        cursor, _settings(), user_id="user-a", model_version="adaface-v2"
    )

    assert result.tau == 0.5
    assert result.threshold_hs == 0.45
    assert result.flagged[0].new_user_threshold == 0.55


def test_raising_tau_never_lowers_an_existing_stricter_override() -> None:
    same_vector = _unit(0)
    cursor = FakeCursor(
        embeddings_by_user={"user-a": [same_vector], "user-b": [same_vector]},
    )
    # user-a already has a stricter override than this run would compute
    # (0.4 = tau(0.35) + margin_hs(0.05)).
    cursor.user_overrides["user-a"] = ("existing-config-id", 0.9)

    run_high_similarity_check_core(
        cursor, _settings(), user_id="user-a", model_version="adaface-v2"
    )

    assert cursor.user_overrides["user-a"] == ("existing-config-id", 0.9)
    # user-b had no prior override, so it IS raised to tau + margin_hs.
    assert cursor.user_overrides["user-b"][1] == pytest.approx(0.4)
