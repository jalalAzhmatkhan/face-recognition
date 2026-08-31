"""Unit tests for `ai_inference.monitoring` (IN-08, FR-MON-04). Pure Python
(the PSI/percentile math + bounded deques) -- no DB/torch/cv2, must pass on
base CI (no `ml` extra). The "synthetic drift scenario" acceptance
criterion (FR-MON-04: "alert terpicu pada skenario uji drift sintetis") is
exercised directly below."""

from ai_inference import metrics, monitoring
from ai_inference.config import Settings
from ai_inference.monitoring import LatencySloDetector, ScoreDriftDetector, UnknownRateDetector

TEST_SETTINGS = Settings(
    monitoring_window_size=5,
    monitoring_min_samples=3,
    score_drift_psi_threshold=0.2,
    unknown_rate_alert_threshold=0.5,
    latency_slo_p95_ms=300,
)


def setup_function() -> None:
    """Every test starts from freshly-configured, empty detectors -- these
    are process-global by design (see module docstring)."""
    monitoring.configure(TEST_SETTINGS)


# --- ScoreDriftDetector ---------------------------------------------------


def test_score_drift_no_alert_while_baseline_still_filling() -> None:
    detector = ScoreDriftDetector(window_size=5, psi_threshold=0.2)
    for score in [0.9, 0.9, 0.9]:
        detector.record(score)
    psi, is_alerting = detector.evaluate()
    assert psi is None
    assert is_alerting is False


def test_score_drift_synthetic_scenario_triggers_alert() -> None:
    """FR-MON-04's literal acceptance criterion: a synthetic drift scenario
    (baseline clustered high-similarity scores, then a sustained shift to
    low-similarity scores) must trigger the alert."""
    detector = ScoreDriftDetector(window_size=5, psi_threshold=0.2)
    for score in [0.9, 0.85, 0.95, 0.9, 0.88]:  # fills + freezes the baseline
        detector.record(score)
    for score in [-0.9, -0.85, -0.95, -0.9, -0.88]:  # fills the rolling window
        detector.record(score)

    psi, is_alerting = detector.evaluate()
    assert psi is not None
    assert psi > 0.2
    assert is_alerting is True


def test_score_drift_no_alert_when_distribution_is_stable() -> None:
    detector = ScoreDriftDetector(window_size=5, psi_threshold=0.2)
    for score in [0.9, 0.85, 0.95, 0.9, 0.88]:
        detector.record(score)
    for score in [0.91, 0.86, 0.94, 0.89, 0.87]:  # same bucket as baseline
        detector.record(score)

    psi, is_alerting = detector.evaluate()
    assert psi is not None
    assert psi == 0.0
    assert is_alerting is False


def test_score_drift_baseline_freezes_after_filling() -> None:
    """Scores recorded AFTER the baseline is full must go to the rolling
    window, never re-fill/replace the baseline."""
    detector = ScoreDriftDetector(window_size=3, psi_threshold=0.2)
    for score in [0.9, 0.9, 0.9]:
        detector.record(score)
    assert list(detector._baseline) == [0.9, 0.9, 0.9]
    detector.record(-0.9)
    assert list(detector._baseline) == [0.9, 0.9, 0.9]  # unchanged
    assert list(detector._recent) == [-0.9]


# --- UnknownRateDetector ---------------------------------------------------


def test_unknown_rate_no_alert_below_min_samples() -> None:
    detector = UnknownRateDetector(window_size=10, rate_threshold=0.5, min_samples=5)
    for _ in range(4):
        detector.record(True)
    rate, is_alerting = detector.evaluate()
    assert rate is None
    assert is_alerting is False


def test_unknown_rate_spike_triggers_alert() -> None:
    detector = UnknownRateDetector(window_size=10, rate_threshold=0.5, min_samples=5)
    for is_unknown in [True, True, True, True, False]:
        detector.record(is_unknown)
    rate, is_alerting = detector.evaluate()
    assert rate == 0.8
    assert is_alerting is True


def test_unknown_rate_normal_traffic_does_not_alert() -> None:
    detector = UnknownRateDetector(window_size=10, rate_threshold=0.5, min_samples=5)
    for is_unknown in [False, False, True, False, False]:
        detector.record(is_unknown)
    rate, is_alerting = detector.evaluate()
    assert rate == 0.2
    assert is_alerting is False


def test_unknown_rate_window_slides() -> None:
    detector = UnknownRateDetector(window_size=3, rate_threshold=0.5, min_samples=3)
    for is_unknown in [True, True, True]:
        detector.record(is_unknown)
    assert detector.evaluate()[0] == 1.0
    detector.record(False)
    detector.record(False)
    detector.record(False)
    assert detector.evaluate()[0] == 0.0


# --- LatencySloDetector -----------------------------------------------------


def test_latency_slo_no_alert_below_min_samples() -> None:
    detector = LatencySloDetector(window_size=10, slo_p95_ms=300, min_samples=5)
    for latency in [100, 100, 100]:
        detector.record(latency)
    p95, is_alerting = detector.evaluate()
    assert p95 is None
    assert is_alerting is False


def test_latency_slo_breach_triggers_alert() -> None:
    detector = LatencySloDetector(window_size=10, slo_p95_ms=300, min_samples=5)
    for latency in [400, 450, 500, 420, 480]:
        detector.record(latency)
    p95, is_alerting = detector.evaluate()
    assert p95 is not None
    assert p95 > 300
    assert is_alerting is True


def test_latency_slo_within_budget_does_not_alert() -> None:
    detector = LatencySloDetector(window_size=10, slo_p95_ms=300, min_samples=5)
    for latency in [50, 60, 55, 45, 70]:
        detector.record(latency)
    p95, is_alerting = detector.evaluate()
    assert p95 is not None
    assert p95 <= 300
    assert is_alerting is False


# --- module-level record_* + Prometheus Gauges -----------------------------


def test_record_similarity_score_updates_gauges_on_synthetic_drift() -> None:
    for score in [0.9, 0.85, 0.95, 0.9, 0.88]:
        monitoring.record_similarity_score(score)
    assert metrics.score_drift_alert._value.get() == 0

    for score in [-0.9, -0.85, -0.95, -0.9, -0.88]:
        monitoring.record_similarity_score(score)
    assert metrics.score_drift_alert._value.get() == 1
    assert metrics.score_drift_psi._value.get() > 0.2


def test_record_decision_updates_unknown_rate_gauges() -> None:
    for decision in ["UNKNOWN", "UNKNOWN", "UNKNOWN", "GRANTED", "UNKNOWN"]:
        monitoring.record_decision(decision)
    assert metrics.unknown_rate._value.get() == 0.8
    assert metrics.unknown_rate_alert._value.get() == 1


def test_record_latency_updates_slo_gauges() -> None:
    for latency_ms in [400, 450, 500, 420, 480]:
        monitoring.record_latency(latency_ms)
    assert metrics.latency_p95_ms._value.get() > 300
    assert metrics.latency_slo_breach_alert._value.get() == 1
