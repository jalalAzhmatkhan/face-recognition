"""Statistical reporting for the edge-case benchmark (EC-TR-01 / TSD-EC D-7,
OQ-8 "rule of 30").

Two independent pieces, both pure-numpy (no scipy dependency, matching this
package's "stay importable without the `ml` extra" convention - see
`ai_training.evaluation.scoring` module docstring):

1. `wilson_ci` - the Wilson score interval for a single binomial proportion
   (e.g. per-slice Recall = correct_genuine / total_genuine). Preferred over
   a naive normal-approximation interval because it stays well-behaved (does
   not exceed [0, 1], does not collapse to zero width) at the small-n / near-0
   or near-1 proportions this project's slices will often see (OQ-8: "bila
   identitas internal terbatas ... laporkan CI Wilson").
2. `bootstrap_recall_ci_by_identity` - a percentile bootstrap that resamples
   IDENTITIES (not individual probes) with replacement. TSD-EC D-7.2 is
   explicit about why: "frame satu orang tidak independen" - probes from the
   same identity are correlated (same lighting rig, same camera session,
   same face), so resampling individual probes would understate the true
   variance. Resampling whole identities (with all their probes carried
   along) respects that correlation structure.
"""

from __future__ import annotations

import math

import numpy as np

# Two-sided z quantiles for the confidence levels this project is expected to
# report at. A tiny fixed table (rather than pulling in scipy for
# `norm.ppf`) - extend if a new confidence level is ever needed.
_Z_FOR_CONFIDENCE: dict[float, float] = {
    0.80: 1.2815515655446004,
    0.90: 1.6448536269514722,
    0.95: 1.9599639845400545,
    0.99: 2.5758293035489004,
}


def _z_for_confidence(confidence: float) -> float:
    try:
        return _Z_FOR_CONFIDENCE[confidence]
    except KeyError as exc:
        supported = ", ".join(str(c) for c in sorted(_Z_FOR_CONFIDENCE))
        raise ValueError(
            f"wilson_ci/bootstrap: unsupported confidence {confidence!r}, "
            f"supported values are: {supported}"
        ) from exc


def wilson_ci(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for `successes / n`, in `[0.0, 1.0]`.

    `n == 0` is a genuinely undefined proportion (no data) - returns the
    widest possible interval `(0.0, 1.0)` rather than raising, so a caller
    computing CIs across many slices/sub-groups (some of which may end up
    empty, e.g. a demographic bucket with zero probes in a small synthetic
    smoke-test slice) can report "no data" without a special-cased branch.
    """
    if n == 0:
        return 0.0, 1.0
    if successes < 0 or successes > n:
        raise ValueError(f"wilson_ci: successes={successes} must be in [0, n={n}]")

    z = _z_for_confidence(confidence)
    phat = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = phat + z2 / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z2 / (4 * n * n))
    lo = (center - margin) / denom
    hi = (center + margin) / denom
    return max(0.0, lo), min(1.0, hi)


def ci_width(ci: tuple[float, float]) -> float:
    """`hi - lo`, used by the no-regression-bertoleransi-CI gate (TSD-EC
    D-7.3 / OQ-8): a candidate fails a critical slice when its Recall drops
    by more than `max(ci_width, 0.02)` (2 percentage points)."""
    lo, hi = ci
    return hi - lo


def bootstrap_recall_ci_by_identity(
    per_identity_outcomes: dict[str, list[bool]],
    *,
    n_resamples: int = 2000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, float]:
    """Percentile bootstrap CI for Recall, resampling BY IDENTITY.

    `per_identity_outcomes` maps `identity -> [is_correct, ...]` for every
    genuine probe of that identity (one bool per probe: True == correctly
    identified). Each bootstrap iteration draws `len(per_identity_outcomes)`
    identities WITH replacement, pools every outcome belonging to the drawn
    identities (an identity drawn twice contributes its probes twice), and
    computes the pooled Recall for that resample. Returns
    `(point_estimate, lo, hi)` where `point_estimate` is the Recall computed
    on the ORIGINAL (non-resampled) data and `(lo, hi)` are the
    `(1-confidence)/2` / `1-(1-confidence)/2` percentiles of the bootstrap
    distribution.

    Raises `ValueError` if there are no identities at all - there is no
    meaningful bootstrap distribution with zero data (same "raise rather
    than silently return zeros" convention as
    `evaluation.latency.measure_embedding_latency_ms`).
    """
    identities = list(per_identity_outcomes.keys())
    if not identities:
        raise ValueError("bootstrap_recall_ci_by_identity: per_identity_outcomes must be non-empty")

    all_outcomes = [o for outcomes in per_identity_outcomes.values() for o in outcomes]
    total = len(all_outcomes)
    point_estimate = (sum(all_outcomes) / total) if total else 0.0

    rng = np.random.default_rng(seed)
    n_identities = len(identities)
    bootstrap_recalls = np.empty(n_resamples, dtype=np.float64)
    for i in range(n_resamples):
        drawn = rng.integers(0, n_identities, size=n_identities)
        pooled_total = 0
        pooled_correct = 0
        for idx in drawn:
            outcomes = per_identity_outcomes[identities[idx]]
            pooled_total += len(outcomes)
            pooled_correct += sum(outcomes)
        bootstrap_recalls[i] = (pooled_correct / pooled_total) if pooled_total else 0.0

    alpha = 1.0 - confidence
    lo = float(np.percentile(bootstrap_recalls, 100 * (alpha / 2)))
    hi = float(np.percentile(bootstrap_recalls, 100 * (1 - alpha / 2)))
    return point_estimate, lo, hi
