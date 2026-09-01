"""Wilson CI + by-identity bootstrap (EC-TR-01 / TSD-EC D-7, OQ-8)."""

from __future__ import annotations

import pytest

from ai_training.evaluation.stats import (
    bootstrap_recall_ci_by_identity,
    ci_width,
    wilson_ci,
)


def test_wilson_ci_no_data_returns_widest_interval() -> None:
    assert wilson_ci(0, 0) == (0.0, 1.0)


def test_wilson_ci_matches_known_reference_values() -> None:
    # Reference values for Wilson score interval, 95% confidence
    # (cross-checked against the standard closed-form formula by hand).
    # n=100, successes=50 -> phat=0.5, a case where the interval is
    # symmetric around ~0.5 with the well-known width for n=100.
    lo, hi = wilson_ci(50, 100, confidence=0.95)
    assert lo == pytest.approx(0.4038, abs=1e-3)
    assert hi == pytest.approx(0.5962, abs=1e-3)


def test_wilson_ci_perfect_proportion_does_not_collapse_to_zero_width() -> None:
    # successes == n (e.g. 20/20 genuine probes correctly recalled) is
    # exactly the small-n / near-1 case the Wilson interval is chosen for -
    # the naive normal approximation would give (1.0, 1.0), a zero-width
    # (overconfident) interval.
    lo, hi = wilson_ci(20, 20)
    assert hi == pytest.approx(1.0)
    assert lo > 0.0
    assert lo < 1.0


def test_wilson_ci_stays_within_bounds() -> None:
    for successes, n in [(0, 5), (5, 5), (1, 3), (30, 600)]:
        lo, hi = wilson_ci(successes, n)
        assert 0.0 <= lo <= hi <= 1.0


def test_wilson_ci_rejects_successes_out_of_range() -> None:
    with pytest.raises(ValueError):
        wilson_ci(6, 5)
    with pytest.raises(ValueError):
        wilson_ci(-1, 5)


def test_wilson_ci_rejects_unsupported_confidence() -> None:
    with pytest.raises(ValueError):
        wilson_ci(1, 2, confidence=0.5)


def test_ci_width() -> None:
    assert ci_width((0.4, 0.6)) == pytest.approx(0.2)


def test_bootstrap_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        bootstrap_recall_ci_by_identity({})


def test_bootstrap_point_estimate_matches_plain_pooled_recall() -> None:
    outcomes = {
        "alice": [True, True, False],
        "bob": [True, False],
        "carol": [True, True, True, True],
    }
    point, lo, hi = bootstrap_recall_ci_by_identity(outcomes, n_resamples=500, seed=1)
    # Pooled: (2 + 1 + 4) correct / (3 + 2 + 4) total = 7/9.
    assert point == pytest.approx(7 / 9)
    assert 0.0 <= lo <= point <= hi <= 1.0


def test_bootstrap_is_deterministic_given_same_seed() -> None:
    outcomes = {"a": [True, False, True], "b": [False, False, True]}
    first = bootstrap_recall_ci_by_identity(outcomes, n_resamples=300, seed=7)
    second = bootstrap_recall_ci_by_identity(outcomes, n_resamples=300, seed=7)
    assert first == second


def test_bootstrap_is_wider_or_equal_when_identities_are_more_heterogeneous() -> None:
    # All identities have identical per-identity recall (0.5) -> resampling
    # identities barely changes the pooled recall -> narrow CI.
    homogeneous = {f"id{i}": [True, False] for i in range(20)}
    # Identities are either all-correct or all-wrong -> which identities get
    # drawn matters a lot -> wide CI.
    heterogeneous = {f"id{i}": [True, True] if i % 2 == 0 else [False, False] for i in range(20)}

    _point_h, lo_h, hi_h = bootstrap_recall_ci_by_identity(homogeneous, n_resamples=1000, seed=3)
    _point_v, lo_v, hi_v = bootstrap_recall_ci_by_identity(heterogeneous, n_resamples=1000, seed=3)

    assert (hi_v - lo_v) > (hi_h - lo_h)


def test_bootstrap_all_zero_identities_have_zero_probes_is_handled() -> None:
    # Degenerate but shouldn't crash: an identity with an empty outcome list.
    outcomes = {"alice": [], "bob": [True, True]}
    point, lo, hi = bootstrap_recall_ci_by_identity(outcomes, n_resamples=200, seed=5)
    assert point == pytest.approx(1.0)
    assert 0.0 <= lo <= hi <= 1.0
