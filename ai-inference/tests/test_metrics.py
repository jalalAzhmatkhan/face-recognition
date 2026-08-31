"""Unit tests for `ai_inference.metrics` (IN-05): the metric OBJECTS
themselves are pure `prometheus_client` constructs with no cv2/torch/DB
involved, so this must pass on base CI (no `ml` extra). Actual wiring into
`run_recognition`/`run_recognition_timed` is exercised live, per this
project's established convention for that class of code (see
`ai_inference.pipeline.recognize`'s module docstring)."""

from prometheus_client import generate_latest

from ai_inference.metrics import decision_latency_seconds, decisions_total, registry


def test_stage_latency_seconds_registered_under_dedicated_registry() -> None:
    families = {family.name for family in registry.collect()}
    assert "inference_stage_latency_seconds" in families


def test_decision_latency_seconds_is_unlabeled_and_observable() -> None:
    decision_latency_seconds.observe(0.042)
    output = generate_latest(registry).decode()
    assert "inference_decision_latency_seconds_bucket" in output


def test_decisions_total_accepts_all_three_outcomes() -> None:
    for outcome in ("GRANTED", "UNKNOWN", "SPOOF_SUSPECTED"):
        decisions_total.labels(decision=outcome).inc()
    output = generate_latest(registry).decode()
    for outcome in ("GRANTED", "UNKNOWN", "SPOOF_SUSPECTED"):
        assert f'decision="{outcome}"' in output


def test_model_loads_total_still_present_after_in05_changes() -> None:
    # Counter family names drop the "_total" suffix in `.collect()` (added
    # back only when rendered via `generate_latest`) -- prometheus_client's
    # own convention, not specific to this metric.
    families = {family.name for family in registry.collect()}
    assert "inference_model_loads" in families
