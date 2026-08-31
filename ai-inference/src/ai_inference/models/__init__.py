"""Model loading abstraction (AdaFace/MediaPipe-backed in production, IN-03).

See ``ai_inference.models.loader`` module docstring for why the production
loader is named ``AdaFaceModelLoader`` (``MLflowModelLoader`` is kept as a
backward-compatible alias, not a distinct implementation).
"""

from ai_inference.models.loader import (
    AdaFaceModelLoader,
    LoadedModel,
    MLflowModelLoader,
    ModelKind,
    ModelLoader,
    StubModelLoader,
    build_model_loader,
)

__all__ = [
    "AdaFaceModelLoader",
    "LoadedModel",
    "MLflowModelLoader",
    "ModelKind",
    "ModelLoader",
    "StubModelLoader",
    "build_model_loader",
]
