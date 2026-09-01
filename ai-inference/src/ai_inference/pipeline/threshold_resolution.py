"""EC-IN-04: 3-layer threshold resolution for the normal/masked decision
path (TSD-edge-cases.md D-4.2, OQ-6): artefact default -> `recognition_configs`
DB override -> env fallback.

Pure Python + a DB-API cursor (via `ai_inference.gallery`) -- no cv2/torch,
importable and unit-testable on base CI, same convention as
`ai_inference.gallery`/`ai_inference.model_switch`.

**Layer 1 (artefact default) is a documented GAP, not a real implementation**:
per OQ-6, the TSD's binding decision is that the per-mode default lives as
METADATA on the MLflow model artefact (so a model rollback atomically rolls
back its calibrated thresholds too). This codebase has no mechanism to read
artefact metadata anywhere yet -- `ai_inference.model_switch.
ProductionVersionCache` only caches the `models.version` STRING, never tags/
metadata, and there is no MLflow client in `ai-inference` at all. Building
that subsystem is out of scope for this task (task brief: "JANGAN bikin
sistem baru besar2an di luar scope") -- `Settings.similarity_threshold`/
`similarity_threshold_masked` (and their margin/min_frames siblings) stand
in for layer 1 AND layer 3 simultaneously (there is no distinct "lower"
layer below them in this codebase), exactly like every other "tune later"
threshold already in `Settings`. See `Settings.dual_mode_threshold_enabled`'s
docstring for the full rationale. Layer 2 (`recognition_configs` override)
IS implemented for real, via `ai_inference.gallery.
get_recognition_config_override`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai_inference.config import Settings


@dataclass(frozen=True)
class ResolvedThreshold:
    """Effective, fully-resolved decision parameters for one mode -- never
    `None` fields (unlike `ai_inference.gallery.get_recognition_config_
    override`'s dict, every field here has already fallen through to a
    concrete value by the time this is constructed)."""

    similarity_threshold: float
    margin: float
    min_frames: int


def artefact_defaults(settings: Settings, mode: str) -> dict[str, float | int]:
    """Layer 1 (OQ-6) stand-in -- see module docstring for why this reads
    `Settings` env vars instead of real MLflow artefact metadata. `mode`
    other than `"masked"` (i.e. `"normal"`, or any unrecognized value)
    resolves to the pre-EC-IN-04 `Settings` fields -- this is the exact
    single-threshold behavior every existing caller/test relies on, so
    `dual_mode_threshold_enabled=False` callers never even reach this
    function (see `ai_inference.pipeline.recognize.run_recognition`), and
    an enabled caller resolving `mode="normal"` gets byte-identical values
    to the pre-EC-IN-04 defaults.
    """
    if mode == "masked":
        return {
            "similarity_threshold": settings.similarity_threshold_masked,
            "margin": settings.margin_threshold_masked,
            "min_frames": settings.min_frames_for_grant_masked,
        }
    return {
        "similarity_threshold": settings.similarity_threshold,
        "margin": settings.margin_threshold,
        "min_frames": settings.min_frames_for_grant,
    }


def resolve_mode_params(
    cursor: Any,
    settings: Settings,
    *,
    mode: str,
    device_class: str | None,
) -> ResolvedThreshold:
    """Effective `(similarity_threshold, margin, min_frames)` for `mode`
    (`"normal"` | `"masked"`), per the 3-layer OQ-6 contract:

    1. artefact default (`artefact_defaults` above -- documented GAP).
    2. `recognition_configs` override, `DEVICE_CLASS > GLOBAL`
       (`ai_inference.gallery.get_recognition_config_override`, `USER`
       scope intentionally excluded -- see that function's docstring). A
       non-`None` field on the matched row wins; a `None` field falls
       through to (1), never to a different scope's row.
    3. env fallback: already folded into (1) here -- there is no distinct
       layer below the artefact-default env vars in this codebase (see
       module docstring). A caller of THIS function never sees `None`:
       every field always resolves to a concrete value.

    Never raises: `get_recognition_config_override` returning `None` (no
    override row at all for this `mode`/`device_class`) simply means every
    field falls through to the artefact default.
    """
    from ai_inference import gallery

    defaults = artefact_defaults(settings, mode)
    override = gallery.get_recognition_config_override(
        cursor, mode=mode, device_class=device_class
    )

    def _effective(field: str) -> float | int:
        if override is not None and override.get(field) is not None:
            return override[field]  # type: ignore[return-value]
        return defaults[field]

    return ResolvedThreshold(
        similarity_threshold=float(_effective("similarity_threshold")),
        margin=float(_effective("margin")),
        min_frames=int(_effective("min_frames")),
    )
