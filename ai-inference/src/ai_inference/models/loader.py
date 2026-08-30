"""Model loader abstraction.

The inference pipeline needs three models (ratified recommendation,
``documentation/research/recommendations.md``):

- detector: SCRFD (face detection + 5 landmarks)
- embedder: AdaFace IR-50/IR-101 (512-d embeddings)
- liveness: MiniFASNet (passive PAD)

Design:

- :class:`ModelLoader` is the interface the pipeline depends on. It loads a
  model *by registered name + version/stage* and reports what is loaded, so
  the atomic blue/green ``{model_version, gallery_version}`` switch (IN-07)
  can be built on top of it later.
- :class:`MLflowModelLoader` is the production implementation skeleton. It
  lazily imports ``mlflow``/``torch`` (heavy, optional extra ``ml``) and will
  resolve artifacts from the MLflow registry. Artifact download / torch
  deserialization is intentionally NOT implemented in the scaffold - no model
  is ever downloaded here.
- :class:`StubModelLoader` is used in dev/CI: it returns inert handles with
  deterministic version strings so the service and its tests run with zero
  heavy dependencies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ai_inference.config import Settings


class ModelKind(StrEnum):
    DETECTOR = "detector"
    EMBEDDER = "embedder"
    LIVENESS = "liveness"


@dataclass(frozen=True)
class LoadedModel:
    """A loaded model handle plus the metadata needed for version pinning."""

    kind: ModelKind
    name: str
    version: str
    handle: Any  # torch.nn.Module / ONNX session in real impls; opaque here.


class ModelLoader(ABC):
    """Loads pipeline models by registered name and version/stage."""

    @abstractmethod
    def load(self, kind: ModelKind, version: str | None = None) -> LoadedModel:
        """Load (or return cached) model of ``kind``.

        ``version`` is an explicit registry version; ``None`` means the
        configured default stage/alias (e.g. ``production``).
        """

    @abstractmethod
    def loaded_versions(self) -> dict[ModelKind, str]:
        """Versions currently loaded, for /healthz and the blue/green switch."""


class StubModelLoader(ModelLoader):
    """No-op loader for dev/CI: never touches the network or disk."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._loaded: dict[ModelKind, LoadedModel] = {}

    def load(self, kind: ModelKind, version: str | None = None) -> LoadedModel:
        resolved = version or f"stub-{self._settings.model_stage_or_version}"
        model = LoadedModel(kind=kind, name=self._model_name(kind), version=resolved, handle=None)
        self._loaded[kind] = model
        return model

    def loaded_versions(self) -> dict[ModelKind, str]:
        return {kind: model.version for kind, model in self._loaded.items()}

    def _model_name(self, kind: ModelKind) -> str:
        return {
            ModelKind.DETECTOR: self._settings.detector_model_name,
            ModelKind.EMBEDDER: self._settings.embedder_model_name,
            ModelKind.LIVENESS: self._settings.liveness_model_name,
        }[kind]


class MLflowModelLoader(ModelLoader):
    """Production loader skeleton backed by the MLflow model registry.

    ``mlflow`` and ``torch`` are imported lazily so this module stays
    importable without the ``ml`` extra installed. Actual artifact resolution
    is implemented in IN-03/IN-07; the scaffold never downloads anything.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._loaded: dict[ModelKind, LoadedModel] = {}

    def load(self, kind: ModelKind, version: str | None = None) -> LoadedModel:
        try:
            import mlflow  # noqa: F401  (lazy heavy import)
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise RuntimeError(
                "MLflowModelLoader requires the 'ml' extra (uv sync --extra ml)."
            ) from exc
        # Implemented in IN-03: mlflow.pyfunc / torch artifact load pinned to
        # {name, version} from settings.mlflow_tracking_uri.
        raise NotImplementedError("MLflow-backed loading lands with IN-03.")

    def loaded_versions(self) -> dict[ModelKind, str]:
        return {kind: model.version for kind, model in self._loaded.items()}


def build_model_loader(settings: Settings) -> ModelLoader:
    """Factory selecting the loader backend from configuration."""
    if settings.model_loader == "mlflow":
        return MLflowModelLoader(settings)
    return StubModelLoader(settings)
