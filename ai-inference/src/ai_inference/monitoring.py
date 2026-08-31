"""IN-08: drift & model monitoring (FR-MON-04: "score-distribution drift,
unknown-rate spikes, latency SLO breaches -> alerts").

**No Alertmanager/Grafana is deployed anywhere in this monorepo** (no
`docker-compose` service, no `.rules.yml`, no scrape config -- `GET
/metrics` is exposition-only, nothing in this repo scrapes it). So unlike a
production deployment where this module's job would be to *feed* an
external alerting system, here it computes each of FR-MON-04's three
signals in-process and exposes BOTH the raw statistic and a `1`/`0`
"is this alerting right now" Gauge (`ai_inference.metrics`,
`inference_*_alert`) -- those Gauges reading `1` ARE the alert, in exactly
the same "a dedicated metric's non-zero value is the observable signal, no
separate notification path" spirit as IN-07's
`inference_model_version_mismatches_total`. A future Alertmanager, if one
is ever deployed, would simply add a rule watching `inference_*_alert == 1`.

Three independent, stateful detectors, each fed by a `record_*` function
called once per completed `/recognize` request (see
`ai_inference.pipeline.recognize`):

- **Score-distribution drift** (`ScoreDriftDetector`): Population Stability
  Index (PSI) between a FROZEN baseline window (the first
  `Settings.monitoring_window_size` recorded top-1 similarity scores since
  this process started or was last `configure()`d) and the current ROLLING
  window of the same size. There is no persisted, offline reference
  distribution anywhere in this codebase (that would need a TR-07
  validation-set artifact this project doesn't build/ship) -- freezing an
  early in-process window as the reference is the pragmatic, fully
  self-contained alternative: it answers "has the live score distribution
  drifted away from how this process behaved when it started up", which is
  exactly the shape a synthetic drift test can exercise deterministically.
- **Unknown-rate spike** (`UnknownRateDetector`): fraction of `UNKNOWN`
  decisions in a rolling window of the last N decisions.
- **Latency SLO breach** (`LatencySloDetector`): p95 of `latency_ms` over a
  rolling window of the last N requests, compared against
  `Settings.latency_slo_p95_ms` (NFR-PRF-01's 300ms budget).

**Process-global state, deliberately** (mirrors `ai_inference.events`'s
fallback buffer, NOT `ai_inference.model_switch`'s per-app-instance cache):
monitoring is inherently about this whole process's observed traffic
stream, not any single request or app instance, so module-level singletons
are the correct scope here -- `configure()` (called once from the app
lifespan) resets them to fresh, empty detectors sized from `Settings`.
"""

from __future__ import annotations

import math
from collections import deque
from typing import TYPE_CHECKING

from ai_inference import metrics

if TYPE_CHECKING:
    from ai_inference.config import Settings

_SCORE_MIN = -1.0
_SCORE_MAX = 1.0
_SCORE_BINS = 10
_PSI_EPSILON = 1e-4


def _population_stability_index(baseline: list[float], recent: list[float]) -> float:
    """PSI between two samples of the same continuous variable, binned into
    `_SCORE_BINS` equal-width buckets over cosine similarity's natural
    range `[_SCORE_MIN, _SCORE_MAX]`. Each bin's proportion is floored at
    `_PSI_EPSILON` so an empty bin in either sample never causes a
    `log(0)`/division-by-zero -- the standard PSI stabilization trick.
    Interpretation: <0.1 no significant shift, 0.1-0.2 moderate, >0.2
    significant (this module's default alert threshold, `Settings.
    score_drift_psi_threshold`)."""
    bin_width = (_SCORE_MAX - _SCORE_MIN) / _SCORE_BINS

    def bucket_index(score: float) -> int:
        idx = int((score - _SCORE_MIN) // bin_width)
        return max(0, min(_SCORE_BINS - 1, idx))

    baseline_counts = [0] * _SCORE_BINS
    for score in baseline:
        baseline_counts[bucket_index(score)] += 1
    recent_counts = [0] * _SCORE_BINS
    for score in recent:
        recent_counts[bucket_index(score)] += 1

    psi = 0.0
    for baseline_count, recent_count in zip(baseline_counts, recent_counts, strict=True):
        baseline_pct = max(baseline_count / len(baseline), _PSI_EPSILON)
        recent_pct = max(recent_count / len(recent), _PSI_EPSILON)
        psi += (recent_pct - baseline_pct) * math.log(recent_pct / baseline_pct)
    return psi


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile, no numpy needed (this module must import
    without the `ml` extra installed)."""
    ordered = sorted(values)
    rank = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[min(rank, len(ordered) - 1)]


class ScoreDriftDetector:
    def __init__(self, window_size: int, psi_threshold: float) -> None:
        self._window_size = window_size
        self._psi_threshold = psi_threshold
        self._baseline: deque[float] = deque()
        self._recent: deque[float] = deque(maxlen=window_size)

    def record(self, score: float) -> None:
        if len(self._baseline) < self._window_size:
            self._baseline.append(score)
            return
        self._recent.append(score)

    def evaluate(self) -> tuple[float | None, bool]:
        """`(psi, is_alerting)`. `psi` is `None` until BOTH the baseline
        and the rolling window are full -- there isn't enough data yet for
        a meaningful comparison."""
        if len(self._baseline) < self._window_size or len(self._recent) < self._window_size:
            return None, False
        psi = _population_stability_index(list(self._baseline), list(self._recent))
        return psi, psi > self._psi_threshold


class UnknownRateDetector:
    def __init__(self, window_size: int, rate_threshold: float, min_samples: int) -> None:
        self._window: deque[bool] = deque(maxlen=window_size)
        self._rate_threshold = rate_threshold
        self._min_samples = min_samples

    def record(self, is_unknown: bool) -> None:
        self._window.append(is_unknown)

    def evaluate(self) -> tuple[float | None, bool]:
        if len(self._window) < self._min_samples:
            return None, False
        rate = sum(self._window) / len(self._window)
        return rate, rate > self._rate_threshold


class LatencySloDetector:
    def __init__(self, window_size: int, slo_p95_ms: float, min_samples: int) -> None:
        self._window: deque[float] = deque(maxlen=window_size)
        self._slo_p95_ms = slo_p95_ms
        self._min_samples = min_samples

    def record(self, latency_ms: float) -> None:
        self._window.append(latency_ms)

    def evaluate(self) -> tuple[float | None, bool]:
        if len(self._window) < self._min_samples:
            return None, False
        p95 = _percentile(list(self._window), 0.95)
        return p95, p95 > self._slo_p95_ms


# Module-level singletons with the same defaults as `Settings` (see that
# module's IN-08 section) so `record_*` below works even for callers (e.g.
# unit tests, or `run_recognition` called directly without an app) that
# never called `configure()` -- mirrors `ai_inference.events`'s
# `_buffer_max_size` module-level default.
_score_drift_detector = ScoreDriftDetector(window_size=100, psi_threshold=0.2)
_unknown_rate_detector = UnknownRateDetector(window_size=100, rate_threshold=0.5, min_samples=20)
_latency_slo_detector = LatencySloDetector(window_size=100, slo_p95_ms=300, min_samples=20)


def configure(settings: Settings) -> None:
    """Replaces all three detectors with fresh, empty ones sized from
    `settings` -- called once from the app lifespan. Resets accumulated
    state (a fresh baseline window, an empty rolling window) rather than
    resizing in place, same rationale as
    `ai_inference.events.configure_buffer`."""
    global _score_drift_detector, _unknown_rate_detector, _latency_slo_detector
    _score_drift_detector = ScoreDriftDetector(
        settings.monitoring_window_size, settings.score_drift_psi_threshold
    )
    _unknown_rate_detector = UnknownRateDetector(
        settings.monitoring_window_size,
        settings.unknown_rate_alert_threshold,
        settings.monitoring_min_samples,
    )
    _latency_slo_detector = LatencySloDetector(
        settings.monitoring_window_size,
        settings.latency_slo_p95_ms,
        settings.monitoring_min_samples,
    )


def record_similarity_score(score: float) -> None:
    """Feeds one top-1 similarity score (from ANY decision outcome, not
    just GRANTED -- see `ai_inference.pipeline.recognize`'s call site for
    why) into the score-drift detector, then updates the Prometheus Gauges
    immediately so `/metrics` always reflects the latest evaluation."""
    _score_drift_detector.record(score)
    psi, is_alerting = _score_drift_detector.evaluate()
    if psi is not None:
        metrics.score_drift_psi.set(psi)
    metrics.score_drift_alert.set(1 if is_alerting else 0)


def record_decision(decision: str) -> None:
    """Feeds one final `/recognize` decision into the unknown-rate
    detector, then updates the Prometheus Gauges."""
    _unknown_rate_detector.record(decision == "UNKNOWN")
    rate, is_alerting = _unknown_rate_detector.evaluate()
    if rate is not None:
        metrics.unknown_rate.set(rate)
    metrics.unknown_rate_alert.set(1 if is_alerting else 0)


def record_latency(latency_ms: float) -> None:
    """Feeds one request's total decision latency into the SLO-breach
    detector, then updates the Prometheus Gauges."""
    _latency_slo_detector.record(latency_ms)
    p95, is_alerting = _latency_slo_detector.evaluate()
    if p95 is not None:
        metrics.latency_p95_ms.set(p95)
    metrics.latency_slo_breach_alert.set(1 if is_alerting else 0)
