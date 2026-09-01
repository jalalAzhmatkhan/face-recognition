"""D-4.4 high-similarity pair check (TSD-edge-cases.md D-4.4, REC 13,
EC-TR-04).

Run at the END of TR-03's enrollment embedding pipeline AND at the end of a
`GALLERY_REEMBED` re-embed for one user: compare the just-written template(s)
against every OTHER identity's gallery. A cross-identity pair scoring above
`(tau - margin_hs)` is a signal the matcher may confuse the two people (twins,
close look-alikes) -- flag it (`identity_similarity_flags`) and tighten both
identities' operating threshold (`recognition_configs` scope=user) so a
future 1:N match needs a higher score to accept either of them.

**Never fails enrollment (acceptance criteria, D-4.4)**: this module's
public entrypoint,`run_high_similarity_check_core`, may raise on a genuine
bug or DB error -- it does NOT swallow exceptions itself. The caller
(`worker.tasks.run_enrollment_qc_core` / `run_gallery_reembed_job_core`) is
responsible for wrapping the call in the same "log and continue" try/except
already used for A-4's synthetic-masked-template generation, which has the
identical never-block-enrollment requirement. Keeping the try/except at the
CALL SITE rather than inside this function matches that existing pattern
(see `worker/tasks.py`'s A-4 comment) and keeps this module's own unit tests
able to assert on real exceptions instead of silently-swallowed ones.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from ai_training.config import Settings
from ai_training.db.audit_repo import insert_audit_log
from ai_training.db.enrollment_repo import Cursor
from ai_training.db.similarity_flags_repo import (
    NORMAL_MODE,
    create_identity_similarity_flag,
    get_global_similarity_threshold,
    get_system_staff_id,
    has_open_flag_for_pair,
    list_gallery_vectors_excluding_user,
    list_own_vectors,
    raise_user_similarity_threshold,
)

logger = logging.getLogger(__name__)

# Same convention as `worker.tasks.ACTOR` / `GALLERY_REEMBED_ACTOR` /
# `BACKFILL_MASKED_ACTOR` -- one system actor string for every audit_logs
# row this pipeline writes, regardless of which caller (TR-03 enrollment vs
# `GALLERY_REEMBED`) triggered it.
ACTOR = "system:ai-training-worker"

_EPS = 1e-12


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Plain-Python cosine similarity (no numpy dependency here -- this
    module must stay importable without the `ml` extra, same constraint as
    `ai_training.evaluation.scoring`, which is why that module's own
    `_cosine_similarity` is not imported/reused instead: it is private to
    that module and takes numpy arrays, whereas this one only ever sees the
    plain `list[float]` shape `face_embeddings.vector` round-trips as via
    the raw-SQL cursor)."""
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    denom = math.sqrt(norm_a) * math.sqrt(norm_b)
    if denom < _EPS:
        return 0.0
    return dot / denom


@dataclass(frozen=True)
class HighSimilarityFlagged:
    """One cross-identity pair this run flagged."""

    other_user_id: str
    score: float
    flag_id: str
    threshold_used: float
    new_user_threshold: float | None
    new_other_user_threshold: float | None


@dataclass(frozen=True)
class HighSimilarityCheckResult:
    tau: float
    margin_hs: float
    threshold_hs: float
    own_template_count: int
    other_users_compared: int
    flagged: list[HighSimilarityFlagged]


def _resolve_tau(cursor: Cursor, settings: Settings, *, mode: str) -> float:
    """2-layer resolution (see `HighSimilaritySettings` docstring for why
    this is 2, not the full OQ-6 3-layer contract): a GLOBAL
    `recognition_configs` override for `mode`, else this module's own
    hardcoded env-fallback-equivalent default."""
    override = get_global_similarity_threshold(cursor, mode=mode)
    if override is not None:
        return override
    return settings.high_similarity.default_similarity_threshold


def run_high_similarity_check_core(
    cursor: Cursor,
    settings: Settings,
    *,
    user_id: str,
    model_version: str,
    mode: str = NORMAL_MODE,
    template_kind: str = "enrolled",
) -> HighSimilarityCheckResult:
    """Run the D-4.4 check for `user_id`'s just-written `template_kind`
    templates under `model_version` against every other identity's gallery.

    Idempotent per open pair (see `has_open_flag_for_pair`): re-running this
    for the same pair while an earlier flag is still unresolved does not
    insert a duplicate row, but DOES still (re-)tighten both users' tau if
    the freshly-observed score would raise it further than the existing
    override -- a later re-embed finding an even higher score than the
    original flag is exactly the case where raising tau again matters most.
    """
    tau = _resolve_tau(cursor, settings, mode=mode)
    margin_hs = settings.high_similarity.margin_hs
    threshold_hs = tau - margin_hs

    own_vectors = list_own_vectors(
        cursor, user_id=user_id, model_version=model_version, template_kind=template_kind
    )
    gallery = list_gallery_vectors_excluding_user(
        cursor, exclude_user_id=user_id, model_version=model_version, template_kind=template_kind
    )

    # Max-fusion per other identity (same "best template wins" methodology
    # as `evaluation.scoring.identify_probe` -- REC 13's concern is whether
    # THE BEST cross-identity match is confusable, not the average one).
    best_score_by_user: dict[str, float] = {}
    for other_user_id, other_vector in gallery:
        for own_vector in own_vectors:
            score = _cosine_similarity(own_vector, other_vector)
            if score > best_score_by_user.get(other_user_id, float("-inf")):
                best_score_by_user[other_user_id] = score

    flagged: list[HighSimilarityFlagged] = []
    for other_user_id, score in best_score_by_user.items():
        if score <= threshold_hs:
            continue

        flag_id: str | None = None
        if not has_open_flag_for_pair(cursor, user_a_id=user_id, user_b_id=other_user_id):
            flag_id = create_identity_similarity_flag(
                cursor, user_a_id=user_id, user_b_id=other_user_id, score=score
            )
            insert_audit_log(
                cursor,
                actor=ACTOR,
                action="identity_similarity.flagged",
                entity=f"identity_similarity_flag:{flag_id}",
                payload={
                    "user_a_id": user_id,
                    "user_b_id": other_user_id,
                    "score": score,
                    "tau": tau,
                    "margin_hs": margin_hs,
                    "threshold_hs": threshold_hs,
                    "model_version": model_version,
                },
            )
        else:
            logger.info(
                "ai_training.similarity.high_similarity_flag_already_open "
                "user_a_id=%s user_b_id=%s score=%.4f",
                user_id,
                other_user_id,
                score,
            )

        new_threshold = min(0.999, tau + margin_hs)
        new_user_threshold: float | None = None
        new_other_user_threshold: float | None = None
        staff_id = get_system_staff_id(cursor)
        if staff_id is not None:
            for target_user_id in (user_id, other_user_id):
                config_id = raise_user_similarity_threshold(
                    cursor,
                    user_id=target_user_id,
                    new_threshold=new_threshold,
                    created_by_staff_id=staff_id,
                )
                insert_audit_log(
                    cursor,
                    actor=ACTOR,
                    action="recognition_config.auto_override",
                    entity=f"recognition_config:{config_id}",
                    payload={
                        "scope": "user",
                        "scope_ref": target_user_id,
                        "mode": mode,
                        "similarity_threshold": new_threshold,
                        "reason": "high_similarity_flag",
                        "paired_with": other_user_id if target_user_id == user_id else user_id,
                    },
                )
            new_user_threshold = new_threshold
            new_other_user_threshold = new_threshold
        else:
            # See `get_system_staff_id`'s docstring -- no ADMIN staff account
            # exists yet to attribute the override to. The flag row above is
            # written regardless; only the tau bump (and its audit entry) is
            # skipped -- but that skip is itself audited, so the gap is
            # discoverable by an operator instead of silent.
            logger.warning(
                "ai_training.similarity.threshold_override_skipped_no_staff "
                "user_a_id=%s user_b_id=%s",
                user_id,
                other_user_id,
            )
            insert_audit_log(
                cursor,
                actor=ACTOR,
                action="recognition_config.auto_override_skipped",
                entity=f"user:{user_id}",
                payload={
                    "reason": "no_admin_staff_account_available",
                    "user_a_id": user_id,
                    "user_b_id": other_user_id,
                    "intended_similarity_threshold": new_threshold,
                },
            )

        flagged.append(
            HighSimilarityFlagged(
                other_user_id=other_user_id,
                score=score,
                flag_id=flag_id or "",
                threshold_used=threshold_hs,
                new_user_threshold=new_user_threshold,
                new_other_user_threshold=new_other_user_threshold,
            )
        )

    return HighSimilarityCheckResult(
        tau=tau,
        margin_hs=margin_hs,
        threshold_hs=threshold_hs,
        own_template_count=len(own_vectors),
        other_users_compared=len(best_score_by_user),
        flagged=flagged,
    )
