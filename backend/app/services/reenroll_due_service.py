"""Re-enrollment-due policy (EC-BE-05, TSD-edge-cases.md A-5).

TSD A-5: "Query terjadwal (Celery beat, backend): user dengan enrollment > 24
bulan ATAU moving-average skor genuine < τ+margin (dari log funnel D-1) ->
tandai `reenroll_due`, tampilkan di UI manajemen enrollment."

Two independent criteria, either one is sufficient to flag a user:

1. **Age**: the user's most recent `ENROLLED` enrollment session's
   `updated_at` (see `app/repositories/enrollments.py::list_last_enrolled_at`
   — same anchor-timestamp convention as `retention_service`) is older than
   `reenroll_due_max_age_months`.
2. **Score drift**: the user's moving-average GENUINE-accept similarity
   score (`access_events.similarity` where `decision=GRANTED`) over the
   trailing `reenroll_due_score_window_days` is below `τ + margin`, computed
   from at least `reenroll_due_min_events_for_score` events (too few events
   is "not enough signal", not "criterion met").

**τ source** (task instructions: "ambil τ dari config/threshold existing
yg relevan"): this reuses the exact resolution order EC-BE-04 already
established for `recognition_configs` (see
`app/services/recognition_config_service.py` module docstring) restricted
to the GLOBAL scope and `mode="normal"` — this job has no per-device-class
or per-user context (it evaluates a user in the abstract, not one specific
recognition decision), so DEVICE_CLASS/USER overrides do not apply here.
Order:
  1. `recognition_configs` row for `(GLOBAL, None, "normal")`, if any, and
     its `similarity_threshold` is not NULL.
  2. `Settings.reenroll_due_similarity_threshold_fallback` (mirrors
     ai-inference's own `similarity_threshold` default of 0.35 as a
     same-ballpark placeholder — backend has no MLflow client and does not
     share ai-inference's env, so it cannot read the "real" OQ-6 artefact
     default described in the TSD).
This module never reads `INF_SIMILARITY_THRESHOLD` directly (that's an
ai-inference-only env var); (2) is backend's own equivalent fallback.

**Idempotency** (acceptance criteria: "job idempotent, run dua kali tidak
duplikat audit"): a user already `reenroll_due=True` is skipped entirely —
no re-check of the criteria, no new `audit_logs` row, and
`reenroll_due_marked_at`/`reenroll_due_reason` are left as they were first
set. This mirrors the "check current state before acting" idempotency
pattern used throughout `app/worker/tasks.py` (see that module's docstring)
rather than a separate idempotency-key table.

**Scope discipline** (acceptance criteria: "tidak ada capture/media baru
yang disentuh"): this module only ever reads `enrollment_sessions`/
`access_events`/`recognition_configs` and writes `users.reenroll_due*` +
one `audit_logs` row per newly-flagged user. It never touches
`media_objects`, `face_embeddings`, or dispatches any capture/QC/training
job.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.models.enums import RecognitionConfigScope
from app.repositories.access_events import AccessEventRepository
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.enrollments import EnrollmentSessionRepository
from app.repositories.recognition_configs import RecognitionConfigRepository
from app.repositories.users import UserRepository

REENROLL_DUE_MARKED_ACTION = "user.reenroll_due_marked"
REENROLL_DUE_ACTOR = "system:reenroll-due-job"

REASON_ENROLLMENT_AGE = "enrollment_age"
REASON_LOW_GENUINE_SCORE = "low_genuine_score"

_RECOGNITION_MODE_NORMAL = "normal"


@dataclass
class ReenrollDueResult:
    """Outcome of one `evaluate_reenroll_due` run, for logging/tests."""

    newly_flagged: int = 0
    already_flagged_skipped: int = 0
    evaluated_active_users: int = 0
    resolved_similarity_threshold: float = 0.0
    flagged_user_ids: list[uuid.UUID] = field(default_factory=list)


def _resolve_similarity_threshold(
    recognition_config_repo: RecognitionConfigRepository,
    *,
    fallback: float,
) -> float:
    """GLOBAL/`normal` τ, or `fallback` — see module docstring."""
    config = recognition_config_repo.get_by_key(
        scope=RecognitionConfigScope.GLOBAL, scope_ref=None, mode=_RECOGNITION_MODE_NORMAL
    )
    if config is not None and config.similarity_threshold is not None:
        return config.similarity_threshold
    return fallback


def evaluate_reenroll_due(
    user_repo: UserRepository,
    enrollment_repo: EnrollmentSessionRepository,
    access_event_repo: AccessEventRepository,
    recognition_config_repo: RecognitionConfigRepository,
    audit_repo: AuditLogRepository,
    *,
    now: datetime,
    max_age_months: int,
    score_window_days: int,
    score_margin: float,
    min_events_for_score: int,
    similarity_threshold_fallback: float,
) -> ReenrollDueResult:
    """Evaluate both A-5 criteria for every ACTIVE user and flag matches.

    Pure function over repositories (same split as
    `retention_service.backfill_retention_expiry`/`purge_expired_media`) so
    it is unit-testable without a live Celery/DB context — see
    `app/worker/tasks.py::reenroll_due_task` for the thin Celery wrapper.
    """
    result = ReenrollDueResult()

    similarity_threshold = _resolve_similarity_threshold(
        recognition_config_repo, fallback=similarity_threshold_fallback
    )
    result.resolved_similarity_threshold = similarity_threshold
    score_ceiling = similarity_threshold + score_margin

    age_cutoff = now - timedelta(days=max_age_months * 30)
    score_window_start = now - timedelta(days=score_window_days)

    last_enrolled_at = enrollment_repo.list_last_enrolled_at()
    genuine_scores = access_event_repo.genuine_score_moving_averages(since=score_window_start)

    active_user_ids = user_repo.list_all_active_ids()

    for user_id in active_user_ids:
        result.evaluated_active_users += 1

        reasons: list[str] = []

        enrolled_at = last_enrolled_at.get(user_id)
        if enrolled_at is not None and enrolled_at < age_cutoff:
            reasons.append(REASON_ENROLLMENT_AGE)

        score_stats = genuine_scores.get(user_id)
        if score_stats is not None:
            avg_score, event_count = score_stats
            if event_count >= min_events_for_score and avg_score < score_ceiling:
                reasons.append(REASON_LOW_GENUINE_SCORE)

        if not reasons:
            continue

        user = user_repo.get(user_id)
        if user is None:
            # Vanished between list_all_active_ids() and here (e.g. a
            # concurrent revoke) — nothing to flag.
            continue

        if user.reenroll_due:
            # Idempotency: already flagged, from this job or another
            # producer (e.g. ai-training's D-4.5 backfill job flagging
            # `video_retention_expired`) — no re-audit, no reason overwrite.
            result.already_flagged_skipped += 1
            continue

        user.reenroll_due = True
        user.reenroll_due_reason = "+".join(reasons)
        user.reenroll_due_marked_at = now
        user_repo.update(user)

        audit_repo.record(
            actor=REENROLL_DUE_ACTOR,
            action=REENROLL_DUE_MARKED_ACTION,
            entity=f"user:{user_id}",
            payload={
                "user_id": str(user_id),
                "reasons": reasons,
                "last_enrolled_at": enrolled_at.isoformat() if enrolled_at else None,
                "genuine_score_avg": score_stats[0] if score_stats else None,
                "genuine_score_event_count": score_stats[1] if score_stats else None,
                "similarity_threshold": similarity_threshold,
                "score_margin": score_margin,
                "score_ceiling": score_ceiling,
                "max_age_months": max_age_months,
                "score_window_days": score_window_days,
            },
        )
        result.newly_flagged += 1
        result.flagged_user_ids.append(user_id)

    return result
