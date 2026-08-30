"""Raw-SQL repo helpers against a mocked DB-API cursor (no real Postgres —
per task instructions, automated tests never touch real Postgres/Redis)."""

from unittest.mock import MagicMock

from ai_training.db.audit_repo import insert_audit_log
from ai_training.db.embedding_repo import upsert_embeddings
from ai_training.db.enrollment_repo import (
    get_latest_finalized_video,
    get_state,
    get_user_id,
    guarded_transition,
)
from ai_training.embedding.extractor import PoseBucketEmbedding


def test_get_state_returns_none_when_no_row() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    assert get_state(cursor, "session-1") is None


def test_get_state_returns_state_value() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = ("QC_RUNNING",)
    assert get_state(cursor, "session-1") == "QC_RUNNING"


def test_get_user_id() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = ("user-1",)
    assert get_user_id(cursor, "session-1") == "user-1"


def test_guarded_transition_succeeds_when_one_row_affected() -> None:
    cursor = MagicMock()
    cursor.rowcount = 1
    assert guarded_transition(
        cursor, "session-1", expected_state="QC_RUNNING", new_state="QC_PASSED"
    )
    cursor.execute.assert_called_once()


def test_guarded_transition_fails_when_zero_rows_affected() -> None:
    """This IS the idempotency check: a duplicate/racing job sees 0 rows
    updated because the session already moved past `expected_state`."""
    cursor = MagicMock()
    cursor.rowcount = 0
    assert not guarded_transition(
        cursor, "session-1", expected_state="QC_RUNNING", new_state="QC_PASSED"
    )


def test_guarded_transition_with_qc_report_serializes_json() -> None:
    cursor = MagicMock()
    cursor.rowcount = 1
    ok = guarded_transition(
        cursor,
        "session-1",
        expected_state="QC_RUNNING",
        new_state="REJECTED_QUALITY",
        qc_report={"overall": "REJECTED_QUALITY"},
    )
    assert ok
    args, _kwargs = cursor.execute.call_args
    assert "qc_report" in args[0]


def test_get_latest_finalized_video_returns_bucket_and_key() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = ("frac-media", "enrollment/u1/s1/rotation.webm")
    assert get_latest_finalized_video(cursor, "session-1") == (
        "frac-media",
        "enrollment/u1/s1/rotation.webm",
    )


def test_upsert_embeddings_deletes_then_inserts() -> None:
    cursor = MagicMock()
    templates = [
        PoseBucketEmbedding(pose_bucket="12", vector=[0.1, 0.2], model_version="stub-v1"),
        PoseBucketEmbedding(pose_bucket="03", vector=[0.3, 0.4], model_version="stub-v1"),
    ]
    count = upsert_embeddings(
        cursor,
        user_id="user-1",
        session_id="session-1",
        model_version="stub-v1",
        embeddings=templates,
    )
    assert count == 2
    # 1 DELETE + 2 INSERTs
    assert cursor.execute.call_count == 3
    delete_call = cursor.execute.call_args_list[0]
    assert "DELETE FROM face_embeddings" in delete_call[0][0]


def test_insert_audit_log_calls_execute_with_action() -> None:
    cursor = MagicMock()
    insert_audit_log(
        cursor, actor="system:ai-training-worker", action="enrollment.qc_passed", entity="x"
    )
    cursor.execute.assert_called_once()
    args, _kwargs = cursor.execute.call_args
    assert "INSERT INTO audit_logs" in args[0]
