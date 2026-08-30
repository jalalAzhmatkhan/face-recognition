"""Pure-numpy open-set 1:N identification scoring (TR-07).

No S3/Postgres/torch/MLflow imports anywhere in this module - it must stay
importable (and testable) on base CI without the `ml` extra. The
orchestration layer that wires this to real media/embedders lives in
`ai_training.evaluation.metrics.evaluate_candidate`.

Methodology (documentation/research/recommendations.md SS5, "Threshold
Tuning"): open-set 1:N identification. A probe's identification score is
the MAX cosine similarity against every enrolled template of every gallery
identity ("max-fusion"). A probe is accepted (assigned an identity) only if
its best score clears an operating threshold tau; otherwise it is UNKNOWN.
tau itself is chosen by `find_threshold_for_fpir_budget`: fix a security
budget on FPIR (how often an impostor is wrongly accepted as *someone*),
then pick the SMALLEST tau that still respects that budget - this maximizes
Recall (genuine acceptance) subject to the security constraint, per
recommendations.md.

Definitions used below (open-set identification, NOT verification):
- Recall = (genuine probes correctly assigned their OWN identity) / (total
  genuine probes). A genuine probe that gets accepted under the WRONG
  identity is a failure here, not a success - this is why Recall cannot be
  computed from FNIR alone without also checking identity correctness.
- FNIR (False Negative Identification Rate) = 1 - Recall.
- FPIR (False Positive Identification Rate) = (impostor probes accepted
  under ANY identity) / (total impostor probes).
- Precision = (accepted probes - genuine or impostor - whose predicted
  identity is correct) / (total accepted probes). An impostor accepted
  under any identity always counts as an incorrect prediction, because its
  true identity is `None` and the prediction never is.
- F1 = harmonic mean of Precision and Recall.
"""

from __future__ import annotations

import numpy as np

# Gallery: identity -> list of L2-normalized template embeddings.
Gallery = dict[str, list[np.ndarray]]
# Probe: (true_identity_or_None_for_impostor, embedding).
Probe = tuple[str | None, np.ndarray]

_EPS = 1e-12


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity. Divides by the actual norms (not assumed == 1)
    so this stays correct even if a caller passes a non-normalized vector,
    while still being exact for the normalized-input contract callers are
    expected to honor."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < _EPS:
        return 0.0
    return float(np.dot(a, b) / denom)


def identify_probe(
    embedding: np.ndarray, gallery: Gallery, threshold: float
) -> tuple[str | None, float]:
    """Max-fusion 1:N identification of one probe against the whole
    gallery.

    Returns `(identity, best_score)` where `identity` is the gallery
    identity whose BEST template scored highest, or `None` (UNKNOWN) if the
    gallery is empty or the best score is below `threshold`. `best_score`
    is always the true best score found (even when it's below threshold),
    so callers can sweep thresholds post-hoc without recomputing scores.
    """
    best_identity: str | None = None
    best_score = float("-inf")
    for identity, templates in gallery.items():
        for template in templates:
            score = _cosine_similarity(embedding, template)
            if score > best_score:
                best_score = score
                best_identity = identity
    if best_identity is None or best_score < threshold:
        return None, (best_score if best_identity is not None else float("-inf"))
    return best_identity, best_score


def compute_identification_metrics(
    probes: list[Probe], gallery: Gallery, threshold: float
) -> dict[str, float]:
    """Run `identify_probe` over every probe and aggregate Recall -> F1 ->
    Precision (project priority order) plus FNIR/FPIR, at a fixed
    `threshold`.

    Counting rules (see module docstring): a genuine probe assigned the
    WRONG identity is a Recall failure, not a partial success. An impostor
    probe accepted under ANY identity is an FPIR failure and also always
    counts as an incorrect (non-genuine) prediction for Precision.
    """
    total_genuine = 0
    correct_genuine = 0
    total_impostor = 0
    accepted_impostor = 0
    total_accepted = 0
    correct_accepted = 0

    for true_identity, embedding in probes:
        predicted, _score = identify_probe(embedding, gallery, threshold)
        if true_identity is not None:
            total_genuine += 1
            if predicted == true_identity:
                correct_genuine += 1
        else:
            total_impostor += 1
            if predicted is not None:
                accepted_impostor += 1

        if predicted is not None:
            total_accepted += 1
            if predicted == true_identity:
                correct_accepted += 1

    recall = (correct_genuine / total_genuine) if total_genuine else 0.0
    fnir = 1.0 - recall if total_genuine else 0.0
    fpir = (accepted_impostor / total_impostor) if total_impostor else 0.0
    precision = (correct_accepted / total_accepted) if total_accepted else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "fnir": fnir,
        "fpir": fpir,
        "total_genuine": float(total_genuine),
        "total_impostor": float(total_impostor),
    }


def find_threshold_for_fpir_budget(
    genuine_scores: list[float], impostor_scores: list[float], fpir_budget: float
) -> float:
    """Smallest tau such that FPIR(tau) <= `fpir_budget`, per
    recommendations.md SS5.

    `genuine_scores` is accepted for API symmetry/future use (e.g. logging
    the resulting Recall at the chosen tau) but is NOT used to pick tau -
    the budget is defined purely in terms of the impostor score
    distribution, by design (a security budget must not depend on how the
    genuine population happens to score).

    Method: FPIR(tau) = fraction of impostor scores >= tau, a
    non-increasing step function of tau that only changes value at the
    observed impostor scores. Let `n = len(impostor_scores)` and
    `k = floor(fpir_budget * n)` be the maximum number of impostor scores
    allowed to sit at-or-above tau. Sorting impostor scores descending,
    setting `tau` to the k-th highest score (1-indexed) makes exactly k
    scores >= tau (assuming no ties), which is the SMALLEST tau achieving
    FPIR <= budget - any smaller tau would let in the (k+1)-th score too.

    Edge cases:
    - `k == 0` (budget too tight to admit even the single worst impostor):
      tau is set strictly above the max impostor score (max + a small
      epsilon) so FPIR(tau) == 0 exactly.
    - `k >= n` (budget covers the whole impostor set): the constraint is
      not binding, so tau is set to the minimum impostor score - the
      loosest threshold that still keeps FPIR <= budget (maximizes
      Recall).
    - No impostor scores at all: the budget is vacuously satisfied by any
      tau; falls back to the minimum genuine score (accept everyone) or
      `0.0` if there is no score data at all.

    This is a simple grid search over the empirical impostor score set
    (not a continuous/analytic optimum) - correct because FPIR is constant
    between consecutive observed impostor scores, so no candidate value
    between them can do better.
    """
    impostor = np.asarray(impostor_scores, dtype=np.float64)
    n = impostor.size
    if n == 0:
        if genuine_scores:
            return float(np.min(np.asarray(genuine_scores, dtype=np.float64)))
        return 0.0

    sorted_desc = np.sort(impostor)[::-1]
    k = int(np.floor(fpir_budget * n))
    if k <= 0:
        return float(sorted_desc[0]) + 1e-9
    if k >= n:
        return float(sorted_desc[-1])
    return float(sorted_desc[k - 1])
