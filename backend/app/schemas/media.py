"""Request/response contracts for `{API_V1_PREFIX}/enrollments/{id}/media/*`
and `.../complete` (BE-06, TSD §7, FR-ENR-02/04/05)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import EnrollmentState


class PresignRequest(BaseModel):
    """`POST /enrollments/{id}/media/presign` request body (TSD §7).

    `content_type` and `size` are validated against a per-`kind` allow-list
    in app/services/media_service.py (not here) so the 422 detail can name
    the specific allowed values/bounds. `sha256` is the client's claimed
    checksum of the bytes it is about to upload — hex-encoded, as produced
    by e.g. the browser `SubtleCrypto.digest("SHA-256", ...)` API.

    `variant` (EC-BE-02, TSD-edge-cases.md D-4.1) is optional — every caller
    that predates this field (or simply doesn't care) omits it, and
    `media_service.request_presign` defaults the stored `MediaObject.variant`
    to `"default"` in that case. It only matters once a later frontend task
    (A-1/A-3, gelombang 3) starts requesting the extra no_glasses/glasses/
    pitch_ext captures.
    """

    kind: Literal["photo", "video"]
    content_type: str = Field(..., min_length=1, max_length=255)
    size: int = Field(..., gt=0)
    sha256: str = Field(..., min_length=64, max_length=64)
    variant: Literal["default", "no_glasses", "glasses", "pitch_ext"] | None = None

    @field_validator("sha256")
    @classmethod
    def _sha256_is_hex(cls, value: str) -> str:
        try:
            int(value, 16)
        except ValueError as exc:
            raise ValueError("sha256 must be a 64-character hex string") from exc
        return value.lower()


class PresignResponse(BaseModel):
    upload_url: str
    s3_key: str
    expires_at: datetime


class CompleteResponse(BaseModel):
    id: uuid.UUID
    state: EnrollmentState
