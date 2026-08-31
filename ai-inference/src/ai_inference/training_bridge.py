"""Bridge from ``ai_inference.config.Settings`` to ``ai_training.config.Settings``.

IN-03 decision (see task brief / CLAUDE.md): ai-inference does not duplicate
detection/alignment/embedding code, it depends on the already-live
``ai_training`` package (path dependency, ``ml`` extra) for it. That code
takes an ``ai_training.config.Settings`` (env-prefixed ``TRN_``), not
``ai_inference.config.Settings`` (env-prefixed ``INF_``) -- in particular
``EmbedderSettings.adaface_arch``/``adaface_weights_path`` only exist on the
``ai_training`` side.

Rather than inventing a second, differently-named set of config knobs for
the same weights file, this module builds an ``ai_training.config.Settings``
the SAME way ``ai-training`` itself does: by reading it straight from the
environment (pydantic-settings picks up ``TRN_*``/``TRN_EMBEDDER__*`` env
vars automatically). An operator who wants ai-inference to load a different
AdaFace checkpoint sets the exact same ``TRN_EMBEDDER__ADAFACE_ARCH`` /
``TRN_EMBEDDER__ADAFACE_WEIGHTS_PATH`` env vars on BOTH services -- no new
config surface to keep in sync.

The one deliberate override: ``ai_training.config.EmbedderSettings.backend``
defaults to ``"stub"`` there (correct for ai-training's own test/CI default),
but ai-inference's whole point in depending on this code is to run the REAL
embedder, so this bridge forces ``backend="adaface"`` regardless of what
``TRN_EMBEDDER__BACKEND`` is set to (or not set at all).

**IN-04 extends the same override to liveness**: ``LivenessSettings.backend``
also defaults to ``"stub"`` on the ai-training side (same test/CI reasoning),
but the whole point of ``/recognize`` calling
``ai_training.liveness.detector.build_liveness_detector`` is to run REAL
anti-spoofing on the main path, so this bridge forces
``backend="minifasnet"`` here too, regardless of ``TRN_LIVENESS__BACKEND``.

Lazily imports ``ai_training`` so this module (and anything importing it)
stays importable without the ``ml`` extra installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_training.config import Settings as TrainingSettings

    from ai_inference.config import Settings as InferenceSettings


def build_training_settings(_inference_settings: InferenceSettings) -> TrainingSettings:
    """Build the ``ai_training.config.Settings`` used to construct the real
    embedder. ``_inference_settings`` is accepted for API symmetry/future use
    (e.g. if a field on the inference side should ever override a training
    field) but is currently unused -- everything comes from ``TRN_*`` env
    vars, per this module's docstring.
    """
    from ai_training.config import Settings as TrainingSettings

    training_settings = TrainingSettings()
    if training_settings.embedder.backend != "adaface":
        training_settings.embedder.backend = "adaface"
    if training_settings.liveness.backend != "minifasnet":
        training_settings.liveness.backend = "minifasnet"
    return training_settings
