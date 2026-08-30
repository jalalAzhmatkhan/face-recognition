"""Pure-numpy open-set 1:N identification scoring (TR-07).

Every assertion here is a value that was hand-computed (see comments) - not
just "greater than zero" - so a matheatical bug in Recall/Precision/F1/
FNIR/FPIR would actually fail a test.
"""

from __future__ import annotations

import numpy as np

from ai_training.evaluation.scoring import (
    compute_identification_metrics,
    find_threshold_for_fpir_budget,
    identify_probe,
)

ALICE = np.array([1.0, 0.0])
BOB = np.array([0.0, 1.0])
GALLERY = {"alice": [ALICE], "bob": [BOB]}


def test_identify_probe_returns_best_matching_identity_above_threshold() -> None:
    identity, score = identify_probe(np.array([1.0, 0.0]), GALLERY, threshold=0.5)
    assert identity == "alice"
    assert np.isclose(score, 1.0)


def test_identify_probe_returns_unknown_when_best_score_below_threshold() -> None:
    # cosine([0, -1], alice) == 0.0, cosine([0, -1], bob) == -1.0 -> best is
    # alice at 0.0, which is below threshold 0.5.
    identity, score = identify_probe(np.array([0.0, -1.0]), GALLERY, threshold=0.5)
    assert identity is None
    assert np.isclose(score, 0.0)


def test_identify_probe_empty_gallery_is_always_unknown() -> None:
    identity, score = identify_probe(np.array([1.0, 0.0]), {}, threshold=-1.0)
    assert identity is None
    assert score == float("-inf")


def test_compute_identification_metrics_matches_hand_calculation() -> None:
    # Constructed so Recall/Precision/F1/FNIR/FPIR are all exact fractions:
    #  1) genuine "alice" probe, correctly matched to alice          -> TP
    #  2) genuine "bob" probe, embedding pulls it to alice (wrong id) -> FN
    #  3) impostor probe, embedding pulls it to alice (false accept)  -> FP
    #  4) impostor probe, embedding matches nobody (score 0 < 0.5)    -> TN
    probes = [
        ("alice", np.array([1.0, 0.0])),
        ("bob", np.array([1.0, 0.0])),
        (None, np.array([1.0, 0.0])),
        (None, np.array([0.0, -1.0])),
    ]

    metrics = compute_identification_metrics(probes, GALLERY, threshold=0.5)

    # Recall = correct_genuine / total_genuine = 1/2
    assert np.isclose(metrics["recall"], 0.5)
    # FNIR = 1 - recall = 1/2
    assert np.isclose(metrics["fnir"], 0.5)
    # FPIR = accepted_impostor / total_impostor = 1/2
    assert np.isclose(metrics["fpir"], 0.5)
    # Precision = correct_accepted / total_accepted = 1/3 (probes 1,2,3 all
    # predicted "alice"; only probe 1 is actually alice)
    assert np.isclose(metrics["precision"], 1.0 / 3.0)
    # F1 = 2PR/(P+R) = 2*(1/3)*(1/2) / (1/3 + 1/2) = 0.4
    assert np.isclose(metrics["f1"], 0.4)
    assert metrics["total_genuine"] == 2.0
    assert metrics["total_impostor"] == 2.0


def test_compute_identification_metrics_empty_probes_is_all_zero() -> None:
    metrics = compute_identification_metrics([], GALLERY, threshold=0.5)
    assert metrics["recall"] == 0.0
    assert metrics["precision"] == 0.0
    assert metrics["f1"] == 0.0
    assert metrics["fnir"] == 0.0
    assert metrics["fpir"] == 0.0


def test_find_threshold_for_fpir_budget_picks_kth_highest_impostor_score() -> None:
    # 10 impostor scores 0.0..0.9; budget=0.1 -> k = floor(0.1*10) = 1 ->
    # tau = the single highest impostor score (0.9), giving FPIR(tau) ==
    # 1/10 == 0.1 exactly (== budget, satisfies "<=").
    impostor_scores = [round(0.1 * i, 1) for i in range(10)]  # 0.0, 0.1, ..., 0.9
    tau = find_threshold_for_fpir_budget([], impostor_scores, fpir_budget=0.1)
    assert np.isclose(tau, 0.9)

    observed_fpir = sum(1 for s in impostor_scores if s >= tau) / len(impostor_scores)
    assert np.isclose(observed_fpir, 0.1)


def test_find_threshold_for_fpir_budget_zero_budget_excludes_every_impostor() -> None:
    impostor_scores = [0.2, 0.5, 0.9]
    tau = find_threshold_for_fpir_budget([], impostor_scores, fpir_budget=0.0)
    assert tau > max(impostor_scores)
    assert sum(1 for s in impostor_scores if s >= tau) == 0


def test_find_threshold_for_fpir_budget_full_budget_admits_every_impostor() -> None:
    impostor_scores = [0.2, 0.5, 0.9]
    tau = find_threshold_for_fpir_budget([], impostor_scores, fpir_budget=1.0)
    assert np.isclose(tau, min(impostor_scores))
    assert sum(1 for s in impostor_scores if s >= tau) == len(impostor_scores)


def test_find_threshold_for_fpir_budget_no_impostors_falls_back_to_min_genuine() -> None:
    tau = find_threshold_for_fpir_budget([0.3, 0.7], [], fpir_budget=0.01)
    assert np.isclose(tau, 0.3)


def test_find_threshold_for_fpir_budget_no_scores_at_all_is_zero() -> None:
    assert find_threshold_for_fpir_budget([], [], fpir_budget=0.01) == 0.0
