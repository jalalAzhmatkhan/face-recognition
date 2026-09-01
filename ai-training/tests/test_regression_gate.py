"""EC-QA-01: per-slice no-regression-bertoleransi-CI promotion gate tests.

Builds `SliceEvalSummary` instances directly (rather than driving the full
`evaluate_slice_e2e` pipeline with synthetic crops) so each test isolates
exactly the gate arithmetic/branching under test - `total_genuine`,
`recall`, and `recall_ci` are the only fields `evaluate_slice_regression_gate`
actually reads.
"""

from __future__ import annotations

import pytest

from ai_training.evaluation.e2e import SliceEvalSummary
from ai_training.evaluation.regression_gate import (
    evaluate_slice_regression_gate,
)
from ai_training.evaluation.slices import SLICE_CATALOG


def _summary(recall: float, ci: tuple[float, float], total_genuine: int = 600) -> SliceEvalSummary:
    correct = round(recall * total_genuine)
    return SliceEvalSummary(
        mode="e2e",
        total_genuine=total_genuine,
        correct_genuine=correct,
        recall=recall,
        recall_ci=ci,
        total_impostor=0,
        accepted_impostor=0,
        fpir=0.0,
        fpir_ci=(0.0, 0.0),
    )


CRITICAL_SLICE = "dark"  # is_gate=True in SLICE_CATALOG
REPORT_ONLY_SLICE = "kontak-kosmetik"  # is_smoke_test=True, is_gate=False


def test_critical_slices_come_from_slice_catalog_not_hardcoded() -> None:
    """Sanity check that the gate's notion of "critical" slices is exactly
    SLICE_CATALOG's is_gate flag - not a separately maintained list."""
    expected_critical = {name for name, spec in SLICE_CATALOG.items() if spec.is_gate}
    assert expected_critical == {"masked-riil", "dark", "hijab", "low-res", "per-demografi-utama"}

    report = evaluate_slice_regression_gate({}, None)
    actual_critical_in_report = {
        name for name, r in report.per_slice.items() if r.is_gate
    }
    assert actual_critical_in_report == expected_critical


def test_every_catalog_slice_appears_in_report() -> None:
    report = evaluate_slice_regression_gate({}, None)
    assert set(report.per_slice.keys()) == set(SLICE_CATALOG.keys())


# --- Direction 1: regression beyond tolerance on a critical slice REJECTS ---


def test_regression_beyond_tolerance_on_critical_slice_fails_gate() -> None:
    # Tight CI (large n) so ci_width < 0.02 and the 2pp floor governs:
    # baseline 0.95, candidate 0.90 -> delta 0.05 > max(ci_width, 0.02).
    baseline = {CRITICAL_SLICE: _summary(0.95, (0.93, 0.97), total_genuine=1000)}
    candidate = {CRITICAL_SLICE: _summary(0.90, (0.88, 0.92), total_genuine=1000)}

    report = evaluate_slice_regression_gate(candidate, baseline)

    assert report.passes is False
    assert CRITICAL_SLICE in report.failed_slices
    result = report.per_slice[CRITICAL_SLICE]
    assert result.status == "fail"
    assert result.delta is not None and result.delta > result.tolerance


def test_regression_beyond_wide_ci_width_fails_even_if_under_2pp_would_not() -> None:
    """When the candidate's own CI is wider than 2pp, tolerance = ci_width,
    not the 2pp floor - a small-sample candidate needs an even BIGGER
    regression relative to its own uncertainty to still fail here, so this
    picks deltas that exceed the (wide) ci_width itself."""
    wide_ci = (0.60, 0.90)  # ci_width = 0.30
    baseline = {CRITICAL_SLICE: _summary(0.95, (0.90, 0.99), total_genuine=1000)}
    candidate = {CRITICAL_SLICE: _summary(0.60, wide_ci, total_genuine=40)}

    report = evaluate_slice_regression_gate(candidate, baseline)

    result = report.per_slice[CRITICAL_SLICE]
    assert result.tolerance == pytest.approx(0.30)  # ci_width dominates the 2pp floor
    assert result.status == "fail"  # delta 0.35 > tolerance 0.30
    assert report.passes is False


# --- Direction 2: within tolerance (or improved) on a critical slice PASSES ---


def test_regression_within_tolerance_on_critical_slice_passes_gate() -> None:
    # delta 0.01 < max(ci_width, 0.02) -> within the 2pp floor tolerance.
    baseline = {CRITICAL_SLICE: _summary(0.95, (0.93, 0.97), total_genuine=1000)}
    candidate = {CRITICAL_SLICE: _summary(0.94, (0.92, 0.96), total_genuine=1000)}

    report = evaluate_slice_regression_gate(candidate, baseline)

    assert report.passes is True
    result = report.per_slice[CRITICAL_SLICE]
    assert result.status == "pass"
    assert CRITICAL_SLICE not in report.failed_slices


def test_candidate_better_than_baseline_passes_gate() -> None:
    baseline = {CRITICAL_SLICE: _summary(0.80, (0.77, 0.83), total_genuine=1000)}
    candidate = {CRITICAL_SLICE: _summary(0.95, (0.93, 0.97), total_genuine=1000)}

    report = evaluate_slice_regression_gate(candidate, baseline)

    assert report.passes is True
    result = report.per_slice[CRITICAL_SLICE]
    assert result.status == "pass"
    assert result.delta is not None and result.delta < 0  # improvement


def test_no_baseline_at_all_passes_every_critical_slice_with_data() -> None:
    """First-ever promotion carve-out, mirroring promote_model's
    is_first_promotion behavior for the overall-Recall gate."""
    candidate = {CRITICAL_SLICE: _summary(0.5, (0.3, 0.7), total_genuine=600)}

    report = evaluate_slice_regression_gate(candidate, None)

    result = report.per_slice[CRITICAL_SLICE]
    assert result.status == "pass_no_baseline"
    assert report.passes is True


# --- Direction 3: non-critical slice regression NEVER blocks -----------------


def test_large_regression_on_non_critical_slice_does_not_block_promotion() -> None:
    assert SLICE_CATALOG[REPORT_ONLY_SLICE].is_gate is False
    baseline = {REPORT_ONLY_SLICE: _summary(0.95, (0.90, 0.99), total_genuine=20)}
    candidate = {REPORT_ONLY_SLICE: _summary(0.10, (0.02, 0.30), total_genuine=20)}

    report = evaluate_slice_regression_gate(candidate, baseline)

    assert report.passes is True
    result = report.per_slice[REPORT_ONLY_SLICE]
    assert result.status == "report_only"
    assert REPORT_ONLY_SLICE not in report.failed_slices
    # Still reported (delta computed), just never gates.
    assert result.delta is not None and result.delta > 0.5


# --- Direction 4: slices with no data are skipped, not silently dropped ------


def test_critical_slice_with_no_candidate_data_is_skipped_not_failed() -> None:
    # masked-riil has no synthesizable data source (EC-OPS-02 pending) -
    # simulate that by simply not including it in candidate_slices.
    report = evaluate_slice_regression_gate({}, {"masked-riil": _summary(0.9, (0.8, 1.0))})

    result = report.per_slice["masked-riil"]
    assert result.status == "skipped_no_data"
    assert "masked-riil" in report.skipped_slices
    assert "masked-riil" not in report.failed_slices
    assert report.passes is True


def test_critical_slice_with_zero_genuine_probes_is_treated_as_no_data() -> None:
    candidate = {CRITICAL_SLICE: _summary(0.0, (0.0, 1.0), total_genuine=0)}
    baseline = {CRITICAL_SLICE: _summary(0.95, (0.9, 0.99), total_genuine=1000)}

    report = evaluate_slice_regression_gate(candidate, baseline)

    assert report.per_slice[CRITICAL_SLICE].status == "skipped_no_data"
    assert report.passes is True


def test_skipped_slices_are_visible_in_report_not_hidden() -> None:
    """Acceptance-criteria requirement: skipped slices must be clearly
    reported, not silently dropped without a trace."""
    report = evaluate_slice_regression_gate({}, None)
    # Every gate-eligible slice with no data ends up in skipped_slices.
    for name, spec in SLICE_CATALOG.items():
        if spec.is_gate:
            assert name in report.skipped_slices
            assert report.per_slice[name].reason  # non-empty explanation
