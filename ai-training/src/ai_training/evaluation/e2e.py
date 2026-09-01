"""End-to-end (detect -> liveness -> decision) evaluation mode (EC-TR-01 /
TSD-EC D-7.5).

`ai_training.evaluation.metrics.evaluate_candidate` (TR-07) evaluates
embedding matching ONLY - a probe is "accepted" purely on cosine-similarity
vs. threshold, liveness never enters the decision. TSD-EC D-7.5 calls this
out explicitly as a gap: the harness needs to ALSO evaluate the actual
production decision path, which additionally requires a liveness pass. This
module adds that second mode without touching `metrics.evaluate_candidate` -
same "per-stage" (embedding-only) report stays available side by side, and
the acceptance criteria explicitly wants BOTH reported (e2e result != per-stage
result must be documented, not silently replaced).

Face detection itself is deliberately NOT re-implemented here: this module
operates on already-ALIGNED crops (`EmbedderInterface`'s documented 112x112
contract), exactly like `evaluation.metrics._embed_media_entry` does today.
For real S3-backed media, a caller detects+aligns exactly the way
`evaluate_candidate` already does before calling into this module; the
synthetic placeholder slices (`ai_training.evaluation.synthetic_slices`)
skip detection entirely by construction (the crop IS the aligned crop).

Both `EmbedderInterface`/`LivenessDetector` here can be the `Stub*`
implementations (pure numpy + hashlib, no `ml` extra needed) - see those
modules' docstrings for what that does and does not prove.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel

from ai_training.evaluation.scoring import Gallery, identify_probe

if TYPE_CHECKING:
    from ai_training.embedding.embedder import EmbedderInterface
    from ai_training.liveness.detector import LivenessDetector

# Full-crop bbox for a 112x112 aligned crop - liveness detectors accept a
# bbox in case they want to crop further, but an already-aligned crop IS the
# face region.
_FULL_CROP_BBOX_XY = (0.0, 0.0)
_FULL_CROP_BBOX_WH = (112.0, 112.0)


class DecisionResult(BaseModel):
    """One probe's outcome under ONE evaluation mode (e2e or per-stage)."""

    true_identity: str | None
    predicted_identity: str | None
    embedding_score: float
    liveness_score: float | None = None  # None in per-stage mode (not evaluated)
    liveness_pass: bool | None = None
    granted: bool  # final accept/reject decision under this mode


def embed_crops_to_gallery(
    embedder: EmbedderInterface, crops_by_identity: dict[str, list[np.ndarray]]
) -> Gallery:
    """Embed every crop for every identity into a `Gallery` (all crops
    become templates - unlike `evaluation.metrics._split_gallery_and_probes`
    this module lets the caller decide the gallery/probe split explicitly,
    since slice manifests are much smaller and the split matters more)."""
    gallery: Gallery = {}
    for identity, crops in crops_by_identity.items():
        gallery[identity] = [np.asarray(embedder.embed(crop), dtype=np.float64) for crop in crops]
    return gallery


def decide_e2e(
    crop: np.ndarray,
    true_identity: str | None,
    gallery: Gallery,
    *,
    embedder: EmbedderInterface,
    liveness: LivenessDetector,
    embedding_threshold: float,
    liveness_threshold: float,
) -> DecisionResult:
    """Full production-shaped decision: liveness must ALSO pass.

    Order matches `documentation/research/recommendations.md`'s pipeline
    (detect -> liveness -> embedding match): liveness is scored first;
    scoring the embedding regardless of liveness outcome (rather than
    short-circuiting) keeps `embedding_score` populated for reporting either
    way, mirroring how `evaluation.scoring.identify_probe` always returns
    the true best score even when it's below threshold.
    """
    liveness_score = liveness.score(crop, _FULL_CROP_BBOX_XY, _FULL_CROP_BBOX_WH)
    liveness_pass = liveness_score >= liveness_threshold

    embedding = np.asarray(embedder.embed(crop), dtype=np.float64)
    identity, score = identify_probe(embedding, gallery, embedding_threshold)

    granted = liveness_pass and identity is not None
    predicted = identity if granted else None
    return DecisionResult(
        true_identity=true_identity,
        predicted_identity=predicted,
        embedding_score=score,
        liveness_score=liveness_score,
        liveness_pass=liveness_pass,
        granted=granted,
    )


def decide_per_stage(
    crop: np.ndarray,
    true_identity: str | None,
    gallery: Gallery,
    *,
    embedder: EmbedderInterface,
    embedding_threshold: float,
) -> DecisionResult:
    """Embedding-matching-only decision (liveness never evaluated) - the
    SAME semantics `evaluation.metrics.evaluate_candidate` already reports,
    reproduced here so a caller can diff it against `decide_e2e` on the
    identical probe set (TSD-EC D-7.5: "hasil e2e != hasil per-stage
    terdokumentasi")."""
    embedding = np.asarray(embedder.embed(crop), dtype=np.float64)
    identity, score = identify_probe(embedding, gallery, embedding_threshold)
    return DecisionResult(
        true_identity=true_identity,
        predicted_identity=identity,
        embedding_score=score,
        granted=identity is not None,
    )


class SliceEvalSummary(BaseModel):
    """Aggregate Recall/FPIR for one evaluation mode ("e2e" or
    "per_stage") over one slice, with Wilson CI. `recall_ci` is `(lo, hi)`
    from `stats.wilson_ci(correct_genuine, total_genuine)`."""

    mode: str
    total_genuine: int
    correct_genuine: int
    recall: float
    recall_ci: tuple[float, float]
    total_impostor: int
    accepted_impostor: int
    fpir: float
    fpir_ci: tuple[float, float]


def _summarize(mode: str, decisions: list[DecisionResult]) -> SliceEvalSummary:
    from ai_training.evaluation.stats import wilson_ci

    genuine = [d for d in decisions if d.true_identity is not None]
    impostor = [d for d in decisions if d.true_identity is None]

    total_genuine = len(genuine)
    correct_genuine = sum(1 for d in genuine if d.predicted_identity == d.true_identity)
    total_impostor = len(impostor)
    accepted_impostor = sum(1 for d in impostor if d.granted)

    recall = (correct_genuine / total_genuine) if total_genuine else 0.0
    fpir = (accepted_impostor / total_impostor) if total_impostor else 0.0

    return SliceEvalSummary(
        mode=mode,
        total_genuine=total_genuine,
        correct_genuine=correct_genuine,
        recall=recall,
        recall_ci=wilson_ci(correct_genuine, total_genuine),
        total_impostor=total_impostor,
        accepted_impostor=accepted_impostor,
        fpir=fpir,
        fpir_ci=wilson_ci(accepted_impostor, total_impostor),
    )


class SliceE2EReport(BaseModel):
    """Both modes reported side by side, plus an explicit `modes_differ`
    flag - the acceptance-criteria requirement that e2e and per-stage
    results be documented as (possibly) different, never silently merged."""

    slice_name: str
    e2e: SliceEvalSummary
    per_stage: SliceEvalSummary
    modes_differ: bool
    bootstrap_recall_e2e: tuple[float, float, float] | None = None


def evaluate_slice_e2e(
    slice_name: str,
    genuine_probe_crops: dict[str, list[np.ndarray]],
    impostor_probe_crops: list[np.ndarray],
    gallery: Gallery,
    *,
    embedder: EmbedderInterface,
    liveness: LivenessDetector,
    embedding_threshold: float,
    liveness_threshold: float,
    bootstrap_seed: int = 42,
) -> SliceE2EReport:
    """Run BOTH decision modes over the same probe set and report both.

    `genuine_probe_crops` maps identity -> probe crops for probes NOT used
    to build `gallery` (caller's responsibility, mirroring
    `evaluation.metrics._split_gallery_and_probes`'s gallery/probe
    disjointness). `impostor_probe_crops` are crops whose true identity
    never appears in `gallery`.
    """
    from ai_training.evaluation.stats import bootstrap_recall_ci_by_identity

    e2e_decisions: list[DecisionResult] = []
    per_stage_decisions: list[DecisionResult] = []
    per_identity_e2e_outcomes: dict[str, list[bool]] = {}

    for identity, crops in genuine_probe_crops.items():
        outcomes: list[bool] = []
        for crop in crops:
            e2e = decide_e2e(
                crop,
                identity,
                gallery,
                embedder=embedder,
                liveness=liveness,
                embedding_threshold=embedding_threshold,
                liveness_threshold=liveness_threshold,
            )
            e2e_decisions.append(e2e)
            outcomes.append(e2e.predicted_identity == identity)

            per_stage_decisions.append(
                decide_per_stage(
                    crop,
                    identity,
                    gallery,
                    embedder=embedder,
                    embedding_threshold=embedding_threshold,
                )
            )
        per_identity_e2e_outcomes[identity] = outcomes

    for crop in impostor_probe_crops:
        e2e_decisions.append(
            decide_e2e(
                crop,
                None,
                gallery,
                embedder=embedder,
                liveness=liveness,
                embedding_threshold=embedding_threshold,
                liveness_threshold=liveness_threshold,
            )
        )
        per_stage_decisions.append(
            decide_per_stage(
                crop, None, gallery, embedder=embedder, embedding_threshold=embedding_threshold
            )
        )

    e2e_summary = _summarize("e2e", e2e_decisions)
    per_stage_summary = _summarize("per_stage", per_stage_decisions)

    bootstrap = None
    if per_identity_e2e_outcomes:
        bootstrap = bootstrap_recall_ci_by_identity(per_identity_e2e_outcomes, seed=bootstrap_seed)

    return SliceE2EReport(
        slice_name=slice_name,
        e2e=e2e_summary,
        per_stage=per_stage_summary,
        modes_differ=(
            e2e_summary.recall != per_stage_summary.recall
            or e2e_summary.fpir != per_stage_summary.fpir
        ),
        bootstrap_recall_e2e=bootstrap,
    )


class MaskedThresholdConfigResult(BaseModel):
    config: str
    description: str
    recall: float
    recall_ci: tuple[float, float]


def run_masked_threshold_experiment(
    masked_probe_crops_by_identity: dict[str, list[np.ndarray]],
    gallery_normal: Gallery,
    gallery_synthetic_masked: Gallery,
    *,
    embedder: EmbedderInterface,
    tau_normal: float,
    tau_masked: float,
) -> list[MaskedThresholdConfigResult]:
    """The OQ-3 / TSD-EC D-7.5 "3-configuration" masked-template experiment:
    for the SAME masked genuine probes, compare Recall under

    - **A**: match against the NORMAL (unmasked) template, at `tau_normal`
      (today's baseline - no masked-aware handling at all).
    - **B**: match against the NORMAL template, at the LOWER `tau_masked`
      (EC-IN-04's documented fallback: "match template normal dgn
      tau_masked + flag low_confidence_masked").
    - **C**: match against the `synthetic_masked` template (EC-TR-02), at
      `tau_normal` (the "give it a template that actually looks masked"
      approach).

    This directly informs OQ-3's threshold-vs-template trade-off - it does
    NOT decide which config to ship (that's a product/security-budget
    decision informed by BOTH this Recall table AND the FPIR impact of
    lowering tau, which is out of scope for a masked-genuine-only Recall
    comparison and must be checked separately against the full impostor
    set).
    """
    from ai_training.evaluation.stats import wilson_ci

    def _recall_for(gallery: Gallery, threshold: float) -> tuple[int, int]:
        total = 0
        correct = 0
        for identity, crops in masked_probe_crops_by_identity.items():
            for crop in crops:
                embedding = np.asarray(embedder.embed(crop), dtype=np.float64)
                predicted, _score = identify_probe(embedding, gallery, threshold)
                total += 1
                if predicted == identity:
                    correct += 1
        return correct, total

    configs = [
        (
            "A_normal_template_tau_normal",
            "Normal template @ tau_normal (baseline)",
            gallery_normal,
            tau_normal,
        ),
        (
            "B_normal_template_tau_masked",
            "Normal template @ tau_masked (lowered)",
            gallery_normal,
            tau_masked,
        ),
        (
            "C_synthetic_masked_template_tau_normal",
            "Synthetic-masked template @ tau_normal",
            gallery_synthetic_masked,
            tau_normal,
        ),
    ]

    results = []
    for name, description, gallery, threshold in configs:
        correct, total = _recall_for(gallery, threshold)
        recall = (correct / total) if total else 0.0
        results.append(
            MaskedThresholdConfigResult(
                config=name,
                description=description,
                recall=recall,
                recall_ci=wilson_ci(correct, total),
            )
        )
    return results
