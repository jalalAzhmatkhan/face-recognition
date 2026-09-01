"""Recognition-config CRUD business logic + the 3-layer threshold resolution
contract (EC-BE-04, TSD-edge-cases.md D-4.2/D-10, OQ-6).

Layering per app/main.py docstring: routers (HTTP) -> services (business
logic) -> repositories (data access). This module owns:
  - the pre-insert `(scope, scope_ref, mode)` duplicate check (routers
    translate `DuplicateConfigError` to 409 — mirrors
    app/services/user_service.py's `DuplicateExternalRefError`),
  - writing an `audit_logs` entry for every create/update/delete (same
    pattern as app/services/access_policy_service.py / device_service.py /
    user_service.py),
  - `resolve_recognition_config`, the KONTRAK a later ai-inference task
    (EC-IN-04) and ai-training task (EC-TR-08) will call to resolve the
    effective recognition policy for one `(scope candidates, mode)` lookup.

=== The 3-layer resolution contract (OQ-6 / D-4.2) ===

Per the TSD's binding OQ-6 decision, this table is NEVER the primary source
of a threshold/margin/min_frames value. The full resolution order for any
one field is:

    1. `artefact.default[mode]`   — metadata on the MLflow model artefact
                                     (embedder calibration curve / liveness
                                     BPCER@APCER calibration). NOT looked up
                                     here — this module has no MLflow
                                     client; the caller (ai-inference/
                                     ai-training) supplies it as this
                                     function's `artefact_defaults`.
    2. `recognition_configs` override — the most SPECIFIC scope that has a
                                     row for `mode`, checked in the fixed
                                     priority USER > DEVICE_CLASS > GLOBAL
                                     (`_SCOPE_PRIORITY` below), regardless of
                                     what order the caller passed
                                     `scope_candidates` in. Only ONE row
                                     (the most specific match) is read — this
                                     function does NOT merge fields across
                                     multiple matching rows of different
                                     scopes. A field left NULL on that one
                                     matched row means "not overridden here",
                                     and falls through to steps 1/3, NOT to
                                     a less-specific `recognition_configs`
                                     row (see TSD D-4.2/D-2.3 wording:
                                     "field yang NULL di override berarti
                                     tidak override, pakai default artefak
                                     model/env fallback").
    3. `INF_SIMILARITY_THRESHOLD` env fallback — last resort, used only for
                                     `similarity_threshold` when neither (1)
                                     nor (2) supplied a value (ai-inference's
                                     `config.py`; not read from here since
                                     this is the backend service, not
                                     ai-inference — the caller applies it).

`resolve_recognition_config` implements step 2 in isolation: given the
caller's `artefact_defaults` for this mode (step 1, may be `{}`/all-None if
unknown) and the ordered scope candidates to check, it returns the merged
"effective" values plus which row (if any) supplied the override, so a
caller can log/trace which policy layer actually decided a given
recognition outcome.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models.enums import RecognitionConfigScope
from app.models.recognition_config import RecognitionConfig
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.recognition_configs import RecognitionConfigRepository

# Fixed resolution priority (most specific first), independent of the order
# scope_candidates are passed in — see module docstring / OQ-6.
_SCOPE_PRIORITY = {
    RecognitionConfigScope.USER: 0,
    RecognitionConfigScope.DEVICE_CLASS: 1,
    RecognitionConfigScope.GLOBAL: 2,
}

_OVERRIDE_FIELDS = ("similarity_threshold", "margin", "liveness_threshold", "min_frames")


class ConfigNotFoundError(Exception):
    """No `recognition_configs` row exists with the given id."""


class DuplicateConfigError(Exception):
    """A row already exists for this `(scope, scope_ref, mode)` key."""

    def __init__(
        self, scope: RecognitionConfigScope, scope_ref: str | None, mode: str
    ) -> None:
        self.scope = scope
        self.scope_ref = scope_ref
        self.mode = mode
        super().__init__(f"{scope.value}:{scope_ref}:{mode}")


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, RecognitionConfigScope):
        return value.value
    return value


def list_configs(
    repo: RecognitionConfigRepository,
    *,
    scope: RecognitionConfigScope | None = None,
    scope_ref: str | None = None,
    mode: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[RecognitionConfig], int]:
    items = repo.list(scope=scope, scope_ref=scope_ref, mode=mode, limit=limit, offset=offset)
    total = repo.count(scope=scope, scope_ref=scope_ref, mode=mode)
    return items, total


def create_config(
    repo: RecognitionConfigRepository,
    audit_repo: AuditLogRepository,
    *,
    scope: RecognitionConfigScope,
    scope_ref: str | None,
    mode: str,
    similarity_threshold: float | None,
    margin: float | None,
    liveness_threshold: float | None,
    min_frames: int | None,
    created_by_staff_id: uuid.UUID,
    actor: str,
) -> RecognitionConfig:
    if repo.get_by_key(scope=scope, scope_ref=scope_ref, mode=mode) is not None:
        raise DuplicateConfigError(scope, scope_ref, mode)

    config = RecognitionConfig(
        scope=scope,
        scope_ref=scope_ref,
        mode=mode,
        similarity_threshold=similarity_threshold,
        margin=margin,
        liveness_threshold=liveness_threshold,
        min_frames=min_frames,
        created_by_staff_id=created_by_staff_id,
    )
    config = repo.create(config)

    audit_repo.record(
        actor=actor,
        action="recognition_config.create",
        entity=f"recognition_config:{config.id}",
        payload={
            "scope": scope.value,
            "scope_ref": scope_ref,
            "mode": mode,
            "similarity_threshold": similarity_threshold,
            "margin": margin,
            "liveness_threshold": liveness_threshold,
            "min_frames": min_frames,
        },
    )
    return config


def update_config(
    repo: RecognitionConfigRepository,
    audit_repo: AuditLogRepository,
    *,
    config_id: uuid.UUID,
    updates: dict[str, Any],
    actor: str,
) -> RecognitionConfig:
    """`updates` MUST come from `RecognitionConfigUpdateRequest.model_dump(
    exclude_unset=True)` (mirrors app/services/access_policy_service.py's
    `update_policy`). Only the delta fields are mutable — see
    `RecognitionConfigUpdateRequest`'s docstring for why scope/scope_ref/mode
    are not."""
    config = repo.get(config_id)
    if config is None:
        raise ConfigNotFoundError(str(config_id))

    for field in _OVERRIDE_FIELDS:
        if field in updates:
            setattr(config, field, updates[field])

    config = repo.update(config)

    audit_repo.record(
        actor=actor,
        action="recognition_config.update",
        entity=f"recognition_config:{config.id}",
        payload={k: _serialize(v) for k, v in updates.items()},
    )
    return config


def delete_config(
    repo: RecognitionConfigRepository,
    audit_repo: AuditLogRepository,
    *,
    config_id: uuid.UUID,
    actor: str,
) -> None:
    config = repo.get(config_id)
    if config is None:
        raise ConfigNotFoundError(str(config_id))

    audit_payload = {
        "scope": config.scope.value,
        "scope_ref": config.scope_ref,
        "mode": config.mode,
    }
    repo.delete(config)

    audit_repo.record(
        actor=actor,
        action="recognition_config.delete",
        entity=f"recognition_config:{config_id}",
        payload=audit_payload,
    )


@dataclass(frozen=True)
class ResolvedRecognitionConfig:
    """Result of `resolve_recognition_config` — the effective value for each
    field plus which `recognition_configs` row (if any) supplied the
    override, for tracing/logging which policy layer decided."""

    similarity_threshold: float | None
    margin: float | None
    liveness_threshold: float | None
    min_frames: int | None
    matched_scope: RecognitionConfigScope | None
    matched_scope_ref: str | None
    matched_config_id: uuid.UUID | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "similarity_threshold": self.similarity_threshold,
            "margin": self.margin,
            "liveness_threshold": self.liveness_threshold,
            "min_frames": self.min_frames,
            "matched_scope": self.matched_scope.value if self.matched_scope else None,
            "matched_scope_ref": self.matched_scope_ref,
            "matched_config_id": (
                str(self.matched_config_id) if self.matched_config_id else None
            ),
        }


def resolve_recognition_config(
    repo: RecognitionConfigRepository,
    scope_candidates: list[tuple[RecognitionConfigScope, str | None]],
    mode: str,
    *,
    artefact_defaults: dict[str, float | int | None] | None = None,
) -> ResolvedRecognitionConfig:
    """Resolve the effective recognition policy for `mode` given a caller-
    supplied set of scope candidates (e.g. a specific `(USER, user_id)`,
    that user's device's `(DEVICE_CLASS, device_class)`, and
    `(GLOBAL, None)`).

    `scope_candidates` may be passed in ANY order and need not include all
    three scopes — this function re-sorts them by the fixed
    USER > DEVICE_CLASS > GLOBAL priority (`_SCOPE_PRIORITY`) before
    searching, and stops at the FIRST candidate that has a matching
    `recognition_configs` row for `mode`. Only that single row's fields are
    used; a NULL field on it is NOT backfilled from a less-specific row —
    it is returned as `None`, meaning "no override, use `artefact_defaults`
    (or the env fallback the caller applies for `similarity_threshold`)"
    per the OQ-6 contract (see module docstring).

    If no candidate has a matching row at all, every field falls through
    to `artefact_defaults` unchanged (`matched_scope` is `None`).

    Example (EC-IN-04's expected call shape — device_class + user known):
        >>> resolve_recognition_config(
        ...     repo,
        ...     [
        ...         (RecognitionConfigScope.USER, str(user_id)),
        ...         (RecognitionConfigScope.DEVICE_CLASS, "attendance"),
        ...         (RecognitionConfigScope.GLOBAL, None),
        ...     ],
        ...     mode="masked",
        ...     artefact_defaults={
        ...         "similarity_threshold": 0.42,
        ...         "margin": 0.05,
        ...         "liveness_threshold": 0.6,
        ...         "min_frames": 3,
        ...     },
        ... )
        ResolvedRecognitionConfig(similarity_threshold=0.5, margin=0.05,
            liveness_threshold=0.6, min_frames=3,
            matched_scope=RecognitionConfigScope.DEVICE_CLASS,
            matched_scope_ref="attendance", matched_config_id=UUID(...))
        # (a DEVICE_CLASS override existed setting only similarity_threshold;
        #  margin/liveness_threshold/min_frames fell through to
        #  artefact_defaults since that row left them NULL)
    """
    defaults = artefact_defaults or {}
    ordered = sorted(
        scope_candidates, key=lambda candidate: _SCOPE_PRIORITY.get(candidate[0], 99)
    )

    match: RecognitionConfig | None = None
    for scope, scope_ref in ordered:
        found = repo.get_by_key(scope=scope, scope_ref=scope_ref, mode=mode)
        if found is not None:
            match = found
            break

    def _effective(field: str) -> Any:
        if match is not None:
            override_value = getattr(match, field)
            if override_value is not None:
                return override_value
        return defaults.get(field)

    return ResolvedRecognitionConfig(
        similarity_threshold=_effective("similarity_threshold"),
        margin=_effective("margin"),
        liveness_threshold=_effective("liveness_threshold"),
        min_frames=_effective("min_frames"),
        matched_scope=match.scope if match is not None else None,
        matched_scope_ref=match.scope_ref if match is not None else None,
        matched_config_id=match.id if match is not None else None,
    )
