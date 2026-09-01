"""Request/response contracts for `{API_V1_PREFIX}/system-parameters/*`.

`EnrollmentQualityParams` is the request body shape AND the value schema
persisted into `system_parameters.value` for the `enrollment_capture_
quality` key — see `app/services/system_parameter_service.py` for the
built-in defaults a missing row falls back to.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EnrollmentQualityParams(BaseModel):
    """Enrollment capture wizard quality gate (frontend live preflight AND
    ai-training's server-side QC gate both resolve against this same
    value). All three fields are required on write — this is a full
    replace, not a partial patch, since the three thresholds only make
    sense together (a `min_brightness` without its matching
    `max_brightness` is not a meaningful partial update)."""

    min_blur_variance: float = Field(
        ..., gt=0, description="Variance-of-Laplacian sharpness floor. Lower = more lenient."
    )
    min_brightness: float = Field(..., ge=0, le=255)
    max_brightness: float = Field(..., ge=0, le=255)

    @model_validator(mode="after")
    def _brightness_range_is_valid(self) -> "EnrollmentQualityParams":
        if self.min_brightness >= self.max_brightness:
            raise ValueError("min_brightness must be less than max_brightness")
        return self


class EnrollmentQualityParamsResponse(EnrollmentQualityParams):
    model_config = ConfigDict(from_attributes=True)

    # `None` on both means "no override has ever been saved — these are the
    # built-in defaults", mirroring `models.slice_gate_report`'s "None =
    # nothing to check yet" convention rather than a fabricated timestamp.
    updated_by: uuid.UUID | None
    updated_at: datetime | None
    is_default: bool
