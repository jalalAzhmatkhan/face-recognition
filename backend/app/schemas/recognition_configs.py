"""Request/response contracts for `{API_V1_PREFIX}/recognition-configs/*`
(EC-BE-04, TSD-edge-cases.md D-4.2/D-10, OQ-6)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import RecognitionConfigScope


class RecognitionConfigCreateRequest(BaseModel):
    scope: RecognitionConfigScope
    # NULL only for scope=GLOBAL; required (device_class value / user id) for
    # DEVICE_CLASS/USER — enforced by `_scope_ref_matches_scope` below, and
    # backstopped by the DB CHECK constraint (see the EC-BE-04 migration).
    scope_ref: str | None = Field(None, max_length=64)
    mode: str = Field(..., min_length=1, max_length=32)
    similarity_threshold: float | None = None
    margin: float | None = None
    liveness_threshold: float | None = None
    min_frames: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def _scope_ref_matches_scope(self) -> "RecognitionConfigCreateRequest":
        if self.scope == RecognitionConfigScope.GLOBAL:
            if self.scope_ref is not None:
                raise ValueError("scope_ref must be omitted/null when scope='global'.")
        elif self.scope_ref is None or not self.scope_ref.strip():
            raise ValueError(f"scope_ref is required when scope='{self.scope.value}'.")
        return self

    @model_validator(mode="after")
    def _at_least_one_override_field(self) -> "RecognitionConfigCreateRequest":
        if (
            self.similarity_threshold is None
            and self.margin is None
            and self.liveness_threshold is None
            and self.min_frames is None
        ):
            raise ValueError(
                "At least one of similarity_threshold, margin, liveness_threshold, "
                "min_frames must be set — an override with every field NULL overrides "
                "nothing."
            )
        return self


class RecognitionConfigUpdateRequest(BaseModel):
    """PATCH semantics: only the delta/override values are mutable.

    `scope`/`scope_ref`/`mode` — the override KEY — are fixed at creation
    (mirrors `AccessPolicyUpdateRequest`'s rationale: changing "what this
    override is for" is modeled as delete + recreate, not an update, so the
    unique-key semantics in app/repositories/recognition_configs.py never
    have to reconcile an in-place key change).

    Any field explicitly set to `null` here clears that override (falls
    through to the artefact default/env fallback) — this is why
    `exclude_unset=True` (not `exclude_none=True`) is used when applying
    these updates, same convention as `AccessPolicyUpdateRequest`.
    """

    similarity_threshold: float | None = None
    margin: float | None = None
    liveness_threshold: float | None = None
    min_frames: int | None = Field(None, ge=1)


class RecognitionConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: RecognitionConfigScope
    scope_ref: str | None
    mode: str
    similarity_threshold: float | None
    margin: float | None
    liveness_threshold: float | None
    min_frames: int | None
    created_by_staff_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class RecognitionConfigListResponse(BaseModel):
    items: list[RecognitionConfigResponse]
    total: int
    limit: int
    offset: int
