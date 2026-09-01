"""End-to-end (detect->liveness->decision) vs per-stage evaluation (EC-TR-01
/ TSD-EC D-7.5) - pure numpy, fake embedder/liveness (no `ml` extra, no
StubEmbedder/StubLivenessDetector hashing noise - see module docstring in
`ai_training.evaluation.e2e` for why hash-based stubs aren't useful for
exercising the DECISION LOGIC itself, as opposed to proving the harness
plumbing runs)."""

from __future__ import annotations

import numpy as np
import pytest

from ai_training.evaluation.e2e import (
    decide_e2e,
    decide_per_stage,
    embed_crops_to_gallery,
    evaluate_slice_e2e,
    run_masked_threshold_experiment,
)


class FakeEmbedder:
    """Embedding IS `crop[:-1]` - lets a test fully control the resulting
    cosine similarity by choosing crop values directly, no real image
    pixels needed. `crop[-1]` is reserved for `FakeLiveness` below."""

    model_version = "fake-v1"

    def embed(self, crop: np.ndarray) -> list[float]:
        return [float(x) for x in crop[:-1]]


class FakeLiveness:
    """Liveness score IS `crop[-1]` - fully test-controlled."""

    model_version = "fake-v1"

    def score(self, crop, bbox_xy, bbox_wh) -> float:
        return float(crop[-1])


def _crop(embedding: list[float], liveness_score: float) -> np.ndarray:
    return np.array([*embedding, liveness_score], dtype=np.float64)


ALICE_TEMPLATE = _crop([1.0, 0.0], 1.0)  # liveness value on templates is irrelevant


def test_embed_crops_to_gallery_uses_embedding_prefix_only() -> None:
    gallery = embed_crops_to_gallery(FakeEmbedder(), {"alice": [ALICE_TEMPLATE]})
    assert list(gallery.keys()) == ["alice"]
    assert np.allclose(gallery["alice"][0], [1.0, 0.0])


def test_decide_e2e_grants_when_liveness_and_embedding_both_pass() -> None:
    gallery = {"alice": [np.array([1.0, 0.0])]}
    probe = _crop([1.0, 0.0], liveness_score=0.9)

    result = decide_e2e(
        probe,
        "alice",
        gallery,
        embedder=FakeEmbedder(),
        liveness=FakeLiveness(),
        embedding_threshold=0.5,
        liveness_threshold=0.5,
    )

    assert result.granted is True
    assert result.predicted_identity == "alice"
    assert result.liveness_pass is True
    assert result.embedding_score == pytest.approx(1.0)


def test_decide_e2e_denies_when_liveness_fails_despite_embedding_match() -> None:
    """The core "e2e != per-stage" scenario: embedding matches perfectly but
    liveness score is below threshold (e.g. a spoof/print attack) - e2e must
    deny even though per-stage (embedding-only) would grant."""
    gallery = {"alice": [np.array([1.0, 0.0])]}
    probe = _crop([1.0, 0.0], liveness_score=0.1)  # good match, fails liveness

    e2e = decide_e2e(
        probe,
        "alice",
        gallery,
        embedder=FakeEmbedder(),
        liveness=FakeLiveness(),
        embedding_threshold=0.5,
        liveness_threshold=0.5,
    )
    per_stage = decide_per_stage(
        probe, "alice", gallery, embedder=FakeEmbedder(), embedding_threshold=0.5
    )

    assert e2e.granted is False
    assert e2e.liveness_pass is False
    # Embedding score is still reported even though liveness failed.
    assert e2e.embedding_score == pytest.approx(1.0)

    assert per_stage.granted is True
    assert per_stage.predicted_identity == "alice"


def test_decide_per_stage_never_populates_liveness_fields() -> None:
    gallery = {"alice": [np.array([1.0, 0.0])]}
    probe = _crop([1.0, 0.0], liveness_score=0.0)
    result = decide_per_stage(
        probe, "alice", gallery, embedder=FakeEmbedder(), embedding_threshold=0.5
    )
    assert result.liveness_score is None
    assert result.liveness_pass is None


def test_evaluate_slice_e2e_reports_modes_differ_when_liveness_changes_outcome() -> None:
    gallery = {"alice": [np.array([1.0, 0.0])]}
    genuine_probes = {
        "alice": [
            _crop([1.0, 0.0], liveness_score=0.9),  # e2e grant, per-stage grant
            _crop([1.0, 0.0], liveness_score=0.1),  # e2e deny, per-stage grant
        ]
    }
    impostor_probes = [_crop([0.0, -1.0], liveness_score=0.9)]

    report = evaluate_slice_e2e(
        "dark",
        genuine_probes,
        impostor_probes,
        gallery,
        embedder=FakeEmbedder(),
        liveness=FakeLiveness(),
        embedding_threshold=0.5,
        liveness_threshold=0.5,
    )

    assert report.slice_name == "dark"
    # per-stage: both genuine probes match -> recall 1.0
    assert report.per_stage.recall == pytest.approx(1.0)
    # e2e: only the liveness-passing probe is correctly granted -> recall 0.5
    assert report.e2e.recall == pytest.approx(0.5)
    assert report.modes_differ is True
    assert report.bootstrap_recall_e2e is not None


def test_evaluate_slice_e2e_modes_agree_when_liveness_never_blocks() -> None:
    gallery = {"alice": [np.array([1.0, 0.0])]}
    genuine_probes = {"alice": [_crop([1.0, 0.0], liveness_score=0.9)]}
    impostor_probes = []

    report = evaluate_slice_e2e(
        "dark",
        genuine_probes,
        impostor_probes,
        gallery,
        embedder=FakeEmbedder(),
        liveness=FakeLiveness(),
        embedding_threshold=0.5,
        liveness_threshold=0.5,
    )

    assert report.e2e.recall == report.per_stage.recall == pytest.approx(1.0)
    assert report.modes_differ is False


def test_run_masked_threshold_experiment_hand_computed() -> None:
    # One masked genuine probe per identity, embedding intentionally
    # DEGRADED vs. the normal template (score 0.6) but a near-perfect match
    # vs. the synthetic-masked template (score 0.95).
    embedder = FakeEmbedder()
    masked_probes = {
        "alice": [_crop([0.6, 0.0], liveness_score=1.0)],  # embedding = [0.6, 0.0]
    }
    gallery_normal = {"alice": [np.array([1.0, 0.0])]}
    gallery_synthetic_masked = {"alice": [np.array([0.6, 0.0])]}

    # cosine([0.6, 0], [1, 0]) == 1.0 (same direction) regardless of
    # magnitude -- so to make tau_normal actually reject config A while
    # config C still accepts, use a genuinely different DIRECTION instead.
    masked_probes = {"alice": [_crop([0.6, 0.8], liveness_score=1.0)]}
    # cosine([0.6,0.8],[1,0]) = 0.6 ; cosine([0.6,0.8],[0.6,0.8]) = 1.0
    gallery_synthetic_masked = {"alice": [np.array([0.6, 0.8])]}

    results = run_masked_threshold_experiment(
        masked_probes,
        gallery_normal,
        gallery_synthetic_masked,
        embedder=embedder,
        tau_normal=0.9,
        tau_masked=0.5,
    )
    by_config = {r.config: r for r in results}

    # A: normal template @ tau_normal=0.9 -> score 0.6 < 0.9 -> reject -> recall 0.
    assert by_config["A_normal_template_tau_normal"].recall == pytest.approx(0.0)
    # B: normal template @ tau_masked=0.5 -> score 0.6 >= 0.5 -> accept -> recall 1.
    assert by_config["B_normal_template_tau_masked"].recall == pytest.approx(1.0)
    # C: synthetic-masked template @ tau_normal=0.9 -> score 1.0 >= 0.9 -> accept -> recall 1.
    assert by_config["C_synthetic_masked_template_tau_normal"].recall == pytest.approx(1.0)
