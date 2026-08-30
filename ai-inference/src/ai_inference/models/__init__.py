"""Model loading abstraction (MLflow registry-backed in production)."""

from ai_inference.models.loader import (
    LoadedModel,
    MLflowModelLoader,
    ModelKind,
    ModelLoader,
    StubModelLoader,
    build_model_loader,
)

__all__ = [
    "LoadedModel",
    "MLflowModelLoader",
    "ModelKind",
    "ModelLoader",
    "StubModelLoader",
    "build_model_loader",
]
