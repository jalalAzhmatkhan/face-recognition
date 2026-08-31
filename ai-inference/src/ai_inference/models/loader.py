"""Model loader abstraction.

The inference pipeline needs three models (ratified recommendation,
``documentation/research/recommendations.md``, with one substitution made
consistently across this project since TR-02 -- see below):

- detector: MediaPipe Face Landmarker (face detection + landmarks), NOT
  SCRFD. SCRFD/InsightFace-py carries a non-commercial license issue; this
  project has used MediaPipe (``ai_training.quality.pose``) everywhere
  since TR-02 instead. Do not reintroduce SCRFD here.
- embedder: AdaFace IR-101 (WebFace12M), 512-d embeddings.
- liveness: not implemented yet (IN-04). See :class:`StubModelLoader`'s
  liveness handling and ``ai_inference.pipeline.recognize`` for the current
  fixed-score placeholder.

Design:

- :class:`ModelLoader` is the interface the pipeline depends on. It loads a
  model *by registered name + version/stage* and reports what is loaded, so
  the atomic blue/green ``{model_version, gallery_version}`` switch (IN-07)
  can be built on top of it later.
- :class:`AdaFaceModelLoader` (IN-03) is the real ``ModelKind.EMBEDDER``
  loader. **Naming/honesty note**: this class used to be called
  ``MLflowModelLoader`` and its ``load()`` raised
  ``NotImplementedError("MLflow-backed loading lands with IN-03")``. IN-03
  implements it for real, but NOT by downloading anything from an MLflow
  model registry -- there isn't one populated with artifacts (TR-06 only
  procured the AdaFace checkpoint as a local file; TR-07 only logs
  evaluation METRICS to MLflow, it never calls ``mlflow.register_model``).
  So for ``ModelKind.EMBEDDER`` this loader actually calls
  ``ai_training.embedding.embedder.build_embedder(...)`` against the local
  checkpoint file, exactly like ai-training's own inference path. Renaming
  to ``AdaFaceModelLoader`` makes that honest. ``MLflowModelLoader`` is kept
  as a backward-compatible alias (same class object) since
  ``Settings.model_loader == "mlflow"`` remains a valid, working config
  value (mapped to this same loader) -- ``"adaface"`` is the more honest
  spelling going forward, both work identically today.
  ``ModelKind.DETECTOR`` resolves to the local MediaPipe ``.task`` asset
  path (no real "loading" needed -- ``ai_training.quality.pose`` opens it
  per-call) and ``ModelKind.LIVENESS`` stays a placeholder version string
  (no real liveness model exists until IN-04).
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


class AdaFaceModelLoader(ModelLoader):
    """Real ``ModelKind.EMBEDDER`` loader (IN-03) -- see module docstring's
    "Naming/honesty note" for why this used to be called ``MLflowModelLoader``
    and why it does NOT actually talk to an MLflow model registry.

    - ``EMBEDDER``: builds ``ai_training.embedding.embedder.build_embedder()``
      against a bridged ``ai_training.config.Settings`` (see
      ``ai_inference.training_bridge``), forced onto the real ``"adaface"``
      backend, and loads the local checkpoint file on first use (the
      embedder itself lazy-loads torch/the weights -- see
      ``AdaFaceEmbedder._get_model``). Requires the ``ml`` extra AND a
      downloaded AdaFace checkpoint (same requirement ai-training has).
    - ``DETECTOR``: MediaPipe Face Landmarker is not an object with a
      version to "load" ahead of time (``ai_training.quality.pose`` opens
      its ``.task`` asset per call) -- this just records the configured
      detector name/version so ``/healthz`` reports something meaningful.
    - ``LIVENESS``: no real model exists until IN-04. Recorded as a
      placeholder version so ``/healthz`` is honest about what's actually
      running (see ``ai_inference.pipeline.recognize.placeholder_liveness``).

    ``ai_training``/``torch``/etc are imported lazily so this module stays
    importable without the ``ml`` extra installed.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._loaded: dict[ModelKind, LoadedModel] = {}
        self._embedder: Any = None  # ai_training.embedding.embedder.EmbedderInterface

    def load(self, kind: ModelKind, version: str | None = None) -> LoadedModel:
        if kind is ModelKind.EMBEDDER:
            embedder = self._get_embedder()
            model = LoadedModel(
                kind=kind,
                name=self._settings.embedder_model_name,
                version=version or embedder.model_version,
                handle=embedder,
            )
        elif kind is ModelKind.DETECTOR:
            model = LoadedModel(
                kind=kind,
                name=self._settings.detector_model_name,
                version=version or "mediapipe-face-landmarker-v1",
                handle=None,
            )
        else:  # ModelKind.LIVENESS -- IN-04 gap, see module docstring.
            model = LoadedModel(
                kind=kind,
                name=self._settings.liveness_model_name,
                version=version or "liveness-placeholder-not-implemented",
                handle=None,
            )
        self._loaded[kind] = model
        return model

    def _get_embedder(self) -> Any:
        if self._embedder is not None:
            return self._embedder
        try:
            import torch  # noqa: F401  (lazy heavy import, actionable error below)
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise RuntimeError(
                "AdaFaceModelLoader requires the 'ml' extra (uv sync --extra ml): torch "
                "(pulled in transitively via the ai-training path dependency)."
            ) from exc
        from ai_training.embedding.embedder import build_embedder

        from ai_inference.training_bridge import build_training_settings

        training_settings = build_training_settings(self._settings)
        self._embedder = build_embedder(training_settings)
        return self._embedder

    def loaded_versions(self) -> dict[ModelKind, str]:
        return {kind: model.version for kind, model in self._loaded.items()}


# Backward-compatible alias: `Settings.model_loader == "mlflow"` still works
# and resolves to this exact class -- see the module docstring's "Naming/
# honesty note" for why the "mlflow" name no longer describes what happens.
MLflowModelLoader = AdaFaceModelLoader


def build_model_loader(settings: Settings) -> ModelLoader:
    """Factory selecting the loader backend from configuration.

    Both ``"mlflow"`` (legacy name, kept for backward compatibility) and
    ``"adaface"`` (the honest spelling, see module docstring) select the
    same :class:`AdaFaceModelLoader`.
    """
    if settings.model_loader in ("mlflow", "adaface"):
        return AdaFaceModelLoader(settings)
    return StubModelLoader(settings)
