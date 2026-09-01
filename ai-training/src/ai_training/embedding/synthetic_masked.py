"""A-4: synthetic masked-face template generation (TSD-edge-cases.md A-4 /
Sec.6 OQ-1), extending TR-02/TR-03's enrollment pipeline.

Given the SAME per-clock-position frames TR-02's `run_quality_check`
already decoded/evaluated (the same `frames_by_position` TR-03's
`embedding.extractor.extract_gallery_embeddings` consumes for the ordinary
`enrolled` templates), this:

1. selects the best source frames near frontal (yaw ~0) and +-30 deg yaw
   (`select_masked_source_frames`) — TSD A-4: "pose profil tidak berguna
   (probe bermasker hampir selalu frontal-ish)", so ONLY these poses are
   useful masked-template sources, unlike TR-03 which uses all 12 clock
   positions,
2. overlays a synthetic mask (`MaskOverlayProvider`, `MaskTheFaceProvider`
   in production) on each source frame, one of `MASK_TYPES` per frame,
3. re-detects landmarks on the MASKED frame (not reused from the
   unmasked detection -- occlusion can shift where the model or overlay
   step considers landmarks to sit), aligns, and embeds it with the SAME
   `EmbedderInterface` TR-03 uses,
4. returns one `SyntheticMaskedTemplate` per combination that succeeded.

**Template count (2-3/user, TSD A-4 acceptance criteria)**: by design this
selects exactly `len(SOURCE_YAW_TARGETS) == 3` source frames (frontal,
+30 deg yaw, -30 deg yaw) and assigns each a mask type by round-robin over
`MASK_TYPES` (2 types) -- frontal gets `MASK_TYPES[0]` ("surgical"), +30
gets `MASK_TYPES[1]` ("cloth_dark"), -30 gets `MASK_TYPES[0]` again. This
is a 1-source-frame-per-mask-combination scheme (not the full 3x2=6 cross
product) specifically so the normal-case output lands at 3 templates
(matching the TSD's "2-3/user", not 6), while both mask types still each
appear at least once per user. When fewer than 3 usable source frames
exist (thin/partial capture), fewer templates are produced -- see
`select_masked_source_frames`'s docstring for why that is accepted
degradation, not an error.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_training.embedding.alignment import align_face
from ai_training.embedding.embedder import EmbedderInterface
from ai_training.quality.mask_overlay import MASK_TYPES, MaskOverlayProvider
from ai_training.quality.pose import detect_face_and_landmarks

if TYPE_CHECKING:
    from ai_training.quality.pipeline import FrameQuality

logger = logging.getLogger(__name__)

# TSD A-4: "frame sumber = frame terbaik pose frontal + +-30 deg yaw".
# Order matters: it is also the round-robin mask-type assignment order in
# generate_synthetic_masked_templates (see module docstring).
SOURCE_YAW_TARGETS: tuple[float, ...] = (0.0, 30.0, -30.0)


@dataclass(frozen=True)
class SyntheticMaskedTemplate:
    pose_bucket: str
    vector: list[float]
    model_version: str
    mask_type: str


def _flatten_candidates(frames_by_position: dict[str, list[FrameQuality]]) -> list[FrameQuality]:
    flattened = [c for candidates in frames_by_position.values() for c in candidates]
    passing = [c for c in flattened if c.passed]
    # Same fallback rule as embedding.sampling.select_best_frames: prefer
    # QC-passing frames, but degrade to the full pool rather than nothing
    # if none passed (shouldn't normally happen -- this function is only
    # ever called after TR-02 already gated overall QC to PASS).
    return passing or flattened


def select_masked_source_frames(
    frames_by_position: dict[str, list[FrameQuality]],
    *,
    yaw_targets: tuple[float, ...] = SOURCE_YAW_TARGETS,
) -> list[FrameQuality]:
    """Pick up to `len(yaw_targets)` frames whose measured yaw is closest
    to each target (TSD A-4: frontal + +-30 deg yaw). Selection is by
    actual per-frame `yaw` value (not by which of the 12 clock-position
    buckets a frame landed in) since the clock positions are 30-degrees-
    of-clock-angle apart, not 30-degrees-of-yaw apart (see
    `ai_training.quality.pose`'s module docstring) -- e.g. clock position
    "11"/"01" sit at yaw = yaw_range_deg * sin(30 deg) = 0.5 * yaw_range,
    not at yaw=30 exactly. Matching on the raw yaw value is what the TSD's
    "+-30 deg yaw" spec actually means.

    Ranked by `(|yaw - target|, -blur)` so the closest pose wins ties by
    sharper frame. Each frame is removed from the pool once selected, so
    3 distinct targets never collapse onto the same single frame when
    more than one candidate is available.

    Returns fewer than `len(yaw_targets)` frames (down to zero) when the
    session has fewer usable frames than targets -- this is accepted
    degradation, NOT an error: the caller
    (`generate_synthetic_masked_templates`) simply produces fewer
    templates, and `ai_training.worker.tasks.run_enrollment_qc_core`
    treats that the same as a total masking failure (enrollment still
    completes, `qc_report.synthetic_templates_generated` just reports the
    smaller/zero count).
    """
    pool = list(_flatten_candidates(frames_by_position))
    selected: list[FrameQuality] = []
    for target in yaw_targets:
        if not pool:
            break
        best = min(pool, key=lambda c: (abs(c.yaw - target), -c.blur))
        selected.append(best)
        pool.remove(best)
    return selected


def generate_synthetic_masked_templates(
    frames_by_position: dict[str, list[FrameQuality]],
    embedder: EmbedderInterface,
    mask_provider: MaskOverlayProvider,
    *,
    session_id: str = "",
) -> list[SyntheticMaskedTemplate]:
    """A-4 core logic. Returns a list of `SyntheticMaskedTemplate` — always
    a list, NEVER raises, even if `mask_provider` itself is fundamentally
    unusable (e.g. `MaskTheFaceProvider` in this sandbox, see
    `ai_training.quality.mask_overlay`'s module docstring) or every single
    combination fails for some other reason. An empty list is a completely
    valid, non-error outcome: "zero synthetic_masked templates for this
    enrollment", never "enrollment failed".

    **Graceful degradation (task requirement)**: every per-combination
    step (mask overlay, landmark re-detection, alignment, embedding) is
    inside its own try/except, mirroring this codebase's other
    "one item's failure must never sink the whole job" idioms (e.g.
    `worker.tasks.run_gallery_reembed_job_core`'s per-session isolation).
    A failing combination is logged and skipped; it is NEVER re-raised.
    This is what lets `ai_training.worker.tasks.run_enrollment_qc_core`
    call this function directly (no extra try/except of its own needed
    around the masking-specific logic, only around the DB write that
    follows) and still guarantee enrollment reaches `ENROLLED` with zero
    `synthetic_masked` templates when masking is entirely unavailable.

    **Occlusion/eyewear synthesis is explicitly OUT of scope here**
    (TSD A-4: "Occlusion/kacamata sintetis TIDAK jadi template", REC
    2.2/5.3) -- this function only ever calls `mask_provider.apply()` with
    values drawn from `ai_training.quality.mask_overlay.MASK_TYPES`
    (`"surgical"`, `"cloth_dark"`); there is no code path here that could
    produce a template from any other kind of occlusion.
    """
    templates: list[SyntheticMaskedTemplate] = []
    sources = select_masked_source_frames(frames_by_position)
    for index, source in enumerate(sources):
        mask_type = MASK_TYPES[index % len(MASK_TYPES)]
        try:
            masked_frame = mask_provider.apply(source.frame, mask_type)
            if masked_frame is None:
                logger.info(
                    "ai_training.embedding.synthetic_masked_skip_no_overlay "
                    "session_id=%s pose_bucket=%s mask_type=%s",
                    session_id,
                    source.position,
                    mask_type,
                )
                continue
            detection = detect_face_and_landmarks(masked_frame)
            if detection is None:
                logger.info(
                    "ai_training.embedding.synthetic_masked_skip_no_landmarks "
                    "session_id=%s pose_bucket=%s mask_type=%s",
                    session_id,
                    source.position,
                    mask_type,
                )
                continue
            aligned = align_face(masked_frame, detection.alignment_landmarks_5pt())
            vector = embedder.embed(aligned)
        except Exception:  # noqa: BLE001 - a masking/embedding failure degrades, never fails enrollment
            logger.warning(
                "ai_training.embedding.synthetic_masked_overlay_failed "
                "session_id=%s pose_bucket=%s mask_type=%s",
                session_id,
                source.position,
                mask_type,
                exc_info=True,
            )
            continue
        templates.append(
            SyntheticMaskedTemplate(
                pose_bucket=source.position,
                vector=vector,
                model_version=embedder.model_version,
                mask_type=mask_type,
            )
        )
    return templates
