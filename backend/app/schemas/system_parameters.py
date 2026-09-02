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
    value). The three image-quality thresholds are required on write — this
    is a full replace, not a partial patch, since they only make sense
    together (a `min_brightness` without its matching `max_brightness` is
    not a meaningful partial update).

    The pose-sensitivity fields below carry DEFAULTS rather than being
    required, for two reasons: they were added after the first overrides had
    already been saved, and a row persisted with only the original three
    keys must keep validating on read (a required field here would 500 every
    GET for any deployment that had already used the menu).
    """

    min_blur_variance: float = Field(
        ..., gt=0, description="Variance-of-Laplacian sharpness floor. Lower = more lenient."
    )
    min_brightness: float = Field(..., ge=0, le=255)
    max_brightness: float = Field(..., ge=0, le=255)

    # --- Head-pose sensitivity (clock-position detection) ------------------
    #
    # These correct the FRONTEND's landmark-ratio pose estimator
    # (`frontend/src/features/enrollment-capture/headPose.ts`), which measures
    # how far the nose sits off the face's midlines and therefore reports a
    # signal proportional to `tan(angle)` scaled by how far the nose
    # PROTRUDES relative to the face's width/height. That protrusion is small
    # -- roughly a third of the eye-to-chin half-height -- so an ungained
    # reading needs ~59 degrees of neck extension to register as "12
    # o'clock", which is past what most people can do and past where the
    # landmark model stays reliable. Sideways, where the head rotates much
    # further comfortably, the same insensitivity is survivable. Hence the
    # reported symptom: only the yaw-dominant positions (2,3,4,8,9,10) ever
    # lit up.
    #
    # ai-training's server-side estimator is `cv2.solvePnP` (real 3D pose, in
    # true degrees) and needs no such correction, which is why these are
    # frontend-only and `pose_tolerance_deg` below is the server-side knob.
    yaw_gain: float = Field(
        2.5,
        gt=0,
        le=20,
        description=(
            "Multiplier on the frontend's normalized yaw before clock-position "
            "matching. Higher = less head turn needed. 1.0 disables the correction."
        ),
    )
    pitch_gain: float = Field(
        3.5,
        gt=0,
        le=20,
        description=(
            "Multiplier on the frontend's normalized pitch. Higher than yaw_gain by "
            "default because a head pitches through a much smaller comfortable range "
            "than it turns."
        ),
    )
    min_pose_radius: float = Field(
        0.55,
        gt=0,
        le=1,
        description=(
            "How far from neutral (0..1, after the gains) a pose must be before it "
            "counts as being AT a clock position rather than still near centre."
        ),
    )
    pose_tolerance_deg: float = Field(
        15.0,
        gt=0,
        le=90,
        description=(
            "Server-side (ai-training) QC only: how many degrees a captured frame's "
            "measured pose may differ from the clock position it was captured for."
        ),
    )

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
