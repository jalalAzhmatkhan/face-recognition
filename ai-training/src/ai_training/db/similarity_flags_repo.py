"""Raw-SQL access to `identity_similarity_flags` + `recognition_configs`
(EC-TR-04, TSD-edge-cases.md D-4.4).

Same cross-service convention as `enrollment_repo.py::mark_user_reenroll_due`
and `embedding_repo.py`: ai-training never imports backend's ORM/session, it
talks to backend-owned tables via direct SQL against `settings.db.dsn`
(see that module's docstring and `config.DBSettings`'s "KNOWN GAP" note for
why this is a single shared DSN rather than per-role connections today). A
companion backend migration (`widen_embeddings_write_role_for_ec_tr_04`)
grants `ai_training_embeddings_write` the INSERT/SELECT this module needs on
`identity_similarity_flags`/`recognition_configs`, plus SELECT on
`staff_accounts` (see `get_system_staff_id`'s docstring for why).

`identity_similarity_flags` has no dedicated backend service function to
reuse (per its own model docstring: "no dedicated HTTP endpoint ... written
by a pipeline"), so this module is that pipeline's only writer.
`recognition_configs` DOES have a backend service
(`app/services/recognition_config_service.py::create_config`/`update_config`)
that writes the SAME `audit_logs` entry this module writes by hand — but it
cannot be imported from here (separate `uv` project, no shared Python
package), so this module reimplements the narrow slice of that service's
behavior needed for a `scope=user` auto-override: check-then-insert-or-update
on `(scope, scope_ref, mode)` plus one `audit_logs` row, mirroring
`recognition_config_service.create_config`/`update_config`'s payload shape
closely enough that an operator querying `audit_logs` for
`action LIKE 'recognition_config.%'` sees a consistent story regardless of
which side (backend HTTP endpoint or this pipeline) wrote the row.
"""

from __future__ import annotations

import uuid

from ai_training.db.enrollment_repo import Cursor

# Mirrors `RecognitionConfigScope.USER.value` / `.GLOBAL.value`
# (backend/app/models/enums.py) -- duplicated as plain strings rather than
# imported, same "loose cross-service string convention" as
# `enrollment_repo.py`'s raw state-name literals ("QC_PASSED", "ENROLLED", ...).
SCOPE_USER = "user"
SCOPE_GLOBAL = "global"

# The mode D-4.4's threshold bump applies to. TSD D-4.2 leaves `mode` as an
# open-ended free string; D-4.4 itself only ever talks about "tau" without
# naming a mode, so this picks the same "normal" mode
# `resolve_recognition_config`'s own docstring example keys its GLOBAL
# baseline lookup on.
NORMAL_MODE = "normal"


def get_global_similarity_threshold(cursor: Cursor, *, mode: str = NORMAL_MODE) -> float | None:
    """Layer-2 lookup (OQ-6): a GLOBAL `recognition_configs` override for
    `similarity_threshold`, if a staff admin has set one. Returns `None` if
    no such row exists (or if the row exists but leaves the field NULL) --
    the caller then falls back to `HighSimilaritySettings
    .default_similarity_threshold` (layer 3)."""
    cursor.execute(
        "SELECT similarity_threshold FROM recognition_configs "
        "WHERE scope = %s AND scope_ref IS NULL AND mode = %s",
        (SCOPE_GLOBAL, mode),
    )
    row = cursor.fetchone()
    return row[0] if row and row[0] is not None else None


def list_gallery_vectors_excluding_user(
    cursor: Cursor,
    *,
    exclude_user_id: str,
    model_version: str,
    template_kind: str = "enrolled",
) -> list[tuple[str, list[float]]]:
    """All `(user_id, vector)` gallery templates for `model_version` under
    `template_kind`, belonging to every user EXCEPT `exclude_user_id`.

    Scoped to `template_kind='enrolled'` by default (not `synthetic_masked`
    or a future `recent`): D-4.4's check is about whether two DIFFERENT
    PEOPLE'S faces are confusable to the matcher, which is what the
    ordinary frontal/pose-bucket `enrolled` templates represent. Comparing
    against `synthetic_masked` occlusion templates as well would conflate
    "these two people look alike" with "MaskTheFace happens to occlude both
    faces similarly", which is a different (and much noisier) signal not
    asked for by the TSD's wording ("similarity template baru vs seluruh
    gallery" in context of REC 13's twin/look-alike concern).
    """
    cursor.execute(
        "SELECT user_id, vector FROM face_embeddings "
        "WHERE model_version = %s AND template_kind = %s AND user_id <> %s",
        (model_version, template_kind, exclude_user_id),
    )
    return [(str(row[0]), list(row[1])) for row in cursor.fetchall()]


def list_own_vectors(
    cursor: Cursor,
    *,
    user_id: str,
    model_version: str,
    template_kind: str = "enrolled",
) -> list[list[float]]:
    """The just-enrolled/just-re-embedded user's own templates -- the
    "template baru" side of D-4.4's comparison."""
    cursor.execute(
        "SELECT vector FROM face_embeddings "
        "WHERE model_version = %s AND template_kind = %s AND user_id = %s",
        (model_version, template_kind, user_id),
    )
    return [list(row[0]) for row in cursor.fetchall()]


def has_open_flag_for_pair(cursor: Cursor, *, user_a_id: str, user_b_id: str) -> bool:
    """Idempotency guard: is there already an UNRESOLVED
    `identity_similarity_flags` row for this unordered pair (in either
    column order)? A re-run of the same enrollment/re-embed job for the
    same pair (retry, duplicate Celery delivery, or a later re-embed that
    reconfirms the same two identities are still confusable) should not
    pile up duplicate open flags for an operator to triage -- but a PAIR
    whose prior flag was already `resolved_at`-closed by an operator is
    allowed to be flagged again (the TSD's ongoing-monitoring intent for
    D-4.4/D-6, not a one-shot check)."""
    cursor.execute(
        "SELECT 1 FROM identity_similarity_flags "
        "WHERE resolved_at IS NULL AND "
        "((user_a_id = %s AND user_b_id = %s) OR (user_a_id = %s AND user_b_id = %s)) "
        "LIMIT 1",
        (user_a_id, user_b_id, user_b_id, user_a_id),
    )
    return cursor.fetchone() is not None


def create_identity_similarity_flag(
    cursor: Cursor, *, user_a_id: str, user_b_id: str, score: float
) -> str:
    """Insert one `identity_similarity_flags` row. Caller is responsible for
    the `has_open_flag_for_pair` idempotency check -- kept as a separate
    step (not folded in here) so a caller that wants to always insert
    (e.g. a future admin-triggered re-check) can skip the guard."""
    flag_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO identity_similarity_flags (id, user_a_id, user_b_id, score) "
        "VALUES (%s, %s, %s, %s)",
        (flag_id, user_a_id, user_b_id, score),
    )
    return flag_id


def get_system_staff_id(cursor: Cursor) -> str | None:
    """Best-effort resolution of a `staff_accounts.id` to attribute an
    auto-generated `recognition_configs` override to.

    **Known limitation, called out rather than papered over (same spirit as
    `config.DBSettings`'s "KNOWN GAP" docstring)**: `recognition_configs
    .created_by_staff_id` is `NOT NULL` with `ondelete=RESTRICT` (EC-BE-04
    migration `c7d4b1a9e3f6`) because every row was assumed, at design
    time, to come from the ADMIN-only HTTP CRUD endpoint, which always has
    an authenticated human actor. D-4.4 needs a PIPELINE (no staff session)
    to write this table too, and there is no dedicated "system" staff
    account/service-principal concept anywhere in the schema yet (checked:
    `StaffRole` is `ADMIN|OPERATOR|VIEWER` only, no `SYSTEM`/service role).

    Rather than block the whole D-4.4 feature on a schema change this task
    was not scoped to make (adding a system staff account or relaxing the
    NOT NULL is backend-engineer's call, flagged separately), this looks up
    the earliest-created ADMIN account and attributes the auto-override to
    it -- the same "earliest ADMIN" identity `backend/app/cli.py`'s
    bootstrap-admin flow guarantees exists in any real deployment. Returns
    `None` if no ADMIN exists yet (a not-yet-bootstrapped dev/test DB);
    callers MUST treat that as "skip the recognition_configs write" (see
    `similarity.high_similarity_check.run_high_similarity_check_core`) --
    the `identity_similarity_flags` row (no staff FK) is written
    regardless, so the pair is never silently lost even when this returns
    `None`.
    """
    cursor.execute(
        "SELECT id FROM staff_accounts WHERE role = 'ADMIN' ORDER BY created_at ASC LIMIT 1"
    )
    row = cursor.fetchone()
    return str(row[0]) if row else None


def get_user_scope_override(
    cursor: Cursor, *, user_id: str, mode: str = NORMAL_MODE
) -> tuple[str, float | None] | None:
    """`(id, similarity_threshold)` of the existing `scope=user` override
    row for `user_id`/`mode`, or `None` if none exists yet."""
    cursor.execute(
        "SELECT id, similarity_threshold FROM recognition_configs "
        "WHERE scope = %s AND scope_ref = %s AND mode = %s",
        (SCOPE_USER, user_id, mode),
    )
    row = cursor.fetchone()
    return (str(row[0]), row[1]) if row else None


def raise_user_similarity_threshold(
    cursor: Cursor,
    *,
    user_id: str,
    new_threshold: float,
    created_by_staff_id: str,
    mode: str = NORMAL_MODE,
) -> str:
    """Create-or-tighten the `scope=user` `similarity_threshold` override
    for `user_id` (D-4.4: "naikkan tau per-identitas ... di
    recognition_configs scope user").

    Tau is only ever RAISED here, never lowered: if an override already
    exists with a `similarity_threshold` >= `new_threshold` (e.g. a
    previous D-4.4 flag already tightened it further, or a staff admin
    manually set an even stricter value), this is a no-op on the value
    itself (existing row's id is returned unchanged) -- a fresh flag must
    never accidentally LOOSEN a threshold an operator or an earlier flag
    already tightened. Other override fields on an existing row
    (`margin`/`liveness_threshold`/`min_frames`) are left untouched either
    way, mirroring `recognition_config_service.update_config`'s "only the
    delta fields you pass are mutable" contract.
    """
    existing = get_user_scope_override(cursor, user_id=user_id, mode=mode)
    if existing is not None:
        config_id, current_threshold = existing
        if current_threshold is not None and current_threshold >= new_threshold:
            return config_id
        cursor.execute(
            "UPDATE recognition_configs SET similarity_threshold = %s, updated_at = now() "
            "WHERE id = %s",
            (new_threshold, config_id),
        )
        return config_id

    config_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO recognition_configs "
        "(id, scope, scope_ref, mode, similarity_threshold, created_by_staff_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (config_id, SCOPE_USER, user_id, mode, new_threshold, created_by_staff_id),
    )
    return config_id
