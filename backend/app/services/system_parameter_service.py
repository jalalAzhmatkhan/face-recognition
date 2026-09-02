"""System Parameter admin-menu business logic.

Layering per app/main.py docstring: routers (HTTP) -> services (business
logic) -> repositories (data access). Currently exposes exactly one
parameter, `enrollment_capture_quality` — the Enrollment capture wizard's
sharpness/brightness gate, tunable because most staff enroll using a
laptop's built-in webcam (lower sharpness than an external camera) rather
than dedicated capture hardware, and because acceptable room lighting
varies a lot across deployment sites. Every value here is a genuinely
uncalibrated starting point (same status as every other quality threshold
in this codebase, e.g. `ai_training.config.QCSettings`'s own "placeholder
pending calibration" docstring) — the whole point of a System Parameter
menu is that ADMIN can retune it from observed results without a redeploy.
"""

import uuid

from app.models.system_parameter import SystemParameter
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.system_parameters import SystemParameterRepository
from app.schemas.system_parameters import EnrollmentQualityParams

ENROLLMENT_QUALITY_KEY = "enrollment_capture_quality"

# Starting defaults loosened for laptop-webcam capture (see task discussion):
# the built-in defaults this project shipped with (blur variance ~60-80,
# brightness 40-60/200-215) were tuned assuming a reasonably sharp external
# camera. A typical laptop webcam's lower-quality sensor/lens and heavier
# JPEG compression routinely produce a noticeably lower variance-of-
# Laplacian even on a perfectly in-focus, well-lit face, so `min_blur_
# variance` is the main lever here.
# Pose-sensitivity defaults are left to the schema (see
# `EnrollmentQualityParams`), so a row saved before those fields existed and
# this built-in default agree on the same starting point.
DEFAULT_ENROLLMENT_QUALITY = EnrollmentQualityParams(
    min_blur_variance=30.0,
    min_brightness=35.0,
    max_brightness=225.0,
)


def get_enrollment_quality_params(
    repo: SystemParameterRepository,
) -> tuple[EnrollmentQualityParams, SystemParameter | None]:
    """Returns the effective params plus the underlying row (`None` if no
    override has ever been saved — caller uses this to set
    `is_default`/`updated_by`/`updated_at` on the response)."""
    row = repo.get(ENROLLMENT_QUALITY_KEY)
    if row is None:
        return DEFAULT_ENROLLMENT_QUALITY, None
    return EnrollmentQualityParams.model_validate(row.value), row


def update_enrollment_quality_params(
    repo: SystemParameterRepository,
    audit_repo: AuditLogRepository,
    *,
    params: EnrollmentQualityParams,
    actor: uuid.UUID,
) -> SystemParameter:
    """`params` is already fully validated (min_brightness < max_brightness,
    all positive/in-range) by `EnrollmentQualityParams` itself before this
    is ever called — this function only persists + audits."""
    row = repo.upsert(
        ENROLLMENT_QUALITY_KEY,
        params.model_dump(),
        updated_by=actor,
    )
    audit_repo.record(
        actor=str(actor),
        action="system_parameter.update",
        entity=f"system_parameter:{ENROLLMENT_QUALITY_KEY}",
        payload=params.model_dump(),
    )
    return row
