"""Idempotency of `run_enrollment_qc_core` (TR-02/TR-03) against a fake
DB cursor — never a real Postgres/Redis, per task instructions.

Only the "session not QC_RUNNING" short-circuit branches are exercised
here: they return before touching S3/`run_quality_check`, so no
cv2/mediapipe/boto3 is needed. The QC_RUNNING -> ... happy path is
integration-shaped (needs a real/synthetic video + the `ml` extra) and is
left to manual verification (see the ai-engineer task's report).
"""

from ai_training.config import Settings
from ai_training.worker.tasks import run_enrollment_qc_core


class FakeCursor:
    """Minimal DB-API-cursor-shaped fake: a tiny in-memory `enrollment_sessions`
    plus an `audit_logs` list to assert against."""

    def __init__(self, state: str | None) -> None:
        self._state = state
        self.audit_entries: list[tuple[str, ...]] = []
        self.rowcount = 0
        self._last_query = ""

    def execute(self, query: str, params: tuple = ()) -> None:
        self._last_query = query
        if query.startswith("SELECT state FROM enrollment_sessions"):
            self._fetch = (self._state,) if self._state is not None else None
        elif query.startswith("INSERT INTO audit_logs"):
            self.audit_entries.append(params)
            self._fetch = None
        else:  # pragma: no cover - not exercised by these tests
            self._fetch = None

    def fetchone(self):
        return self._fetch


def _settings() -> Settings:
    return Settings(_env_file=None)


def test_skips_when_session_not_found() -> None:
    cursor = FakeCursor(state=None)
    outcome = run_enrollment_qc_core(cursor, _settings(), "missing-session")
    assert outcome == "skipped_not_found"
    assert len(cursor.audit_entries) == 1
    # audit_logs insert params are (id, actor, action, entity, payload).
    assert cursor.audit_entries[0][2] == "job.qc_skipped"


def test_skips_duplicate_delivery_after_already_passed() -> None:
    cursor = FakeCursor(state="QC_PASSED")
    outcome = run_enrollment_qc_core(cursor, _settings(), "session-1")
    assert outcome == "skipped_wrong_state"
    assert len(cursor.audit_entries) == 1
    assert cursor.audit_entries[0][2] == "job.qc_skipped"


def test_skips_duplicate_delivery_after_rejected() -> None:
    cursor = FakeCursor(state="REJECTED_QUALITY")
    outcome = run_enrollment_qc_core(cursor, _settings(), "session-1")
    assert outcome == "skipped_wrong_state"


def test_is_safe_to_call_twice_for_the_same_terminal_session() -> None:
    """A duplicate .delay() for an already-ENROLLED session is a no-op both
    times — this is the concrete guarantee backend's qc_queue.py relies on
    when it swallows dispatch errors and may retry."""
    cursor = FakeCursor(state="ENROLLED")
    first = run_enrollment_qc_core(cursor, _settings(), "session-1")
    second = run_enrollment_qc_core(cursor, _settings(), "session-1")
    assert first == second == "skipped_wrong_state"
    assert len(cursor.audit_entries) == 2
