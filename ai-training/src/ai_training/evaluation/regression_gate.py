"""Per-slice no-regression-bertoleransi-CI promotion gate (EC-QA-01 /
TSD-EC D-7.3).

Extends the existing overall-Recall promotion gate ("QA-06/QA-07" -
`backend.app.services.training_service.promote_model`'s
no-recall-regression-vs-current-PRODUCTION check, FR-TRN-05) with a SECOND,
finer-grained check: a candidate can pass the overall-Recall gate while
still regressing badly on one specific critical condition (e.g. `dark` or
`masked-riil`) if that condition is a small slice of the frozen benchmark.
TSD-EC D-7.3 calls for gating each CRITICAL slice independently, with a
tolerance band rather than a strict "must not regress at all" rule -
Wilson-CI-sized noise at typical slice sample counts (OQ-8's ~600-1000
genuine decisions) would otherwise fail candidates on pure sampling noise.

**Gate rule** (TSD-EC D-7.3, literally): a candidate FAILS a critical slice
when `baseline_recall - candidate_recall > max(ci_width(candidate), 0.02)`
(2 percentage points). Passing (including candidates that IMPROVE Recall)
requires the regression to stay within that tolerance. `ci_width` comes
from `ai_training.evaluation.stats.ci_width`, applied to the CANDIDATE's
Wilson CI (the interval the caller is meant to trust for the number that
matters here - how uncertain the CANDIDATE's own point estimate is at its
sample size); this is a documented interpretation, not the only reading of
"lebar CI" in the TSD, since the baseline's CI could arguably also be
consulted. Reusing `SLICE_CATALOG` from `ai_training.evaluation.slices` is
deliberate - the catalog is model+the single source of truth for which
slices are critical/is_gate=True (masked-riil, dark, low-res, hijab,
per-demografi-utama as of EC-TR-01); this module does NOT re-declare that
list.

**Statuses** a slice can end up with in the report:
  - `"skipped_no_data"` - no candidate evaluation data at all for this
    slice (`total_genuine == 0` or the slice key missing from the input
    dict). Per task instructions this must NEVER silently fail the gate -
    every EC-TR-01 critical slice except the `synthesizable` ones has
    `data_status="awaiting_real_data"` (EC-OPS-02 not yet run), so today
    most critical slices legitimately have no real data and must be
    reported as skipped, not passed or failed.
  - `"report_only"` - the slice is not `is_gate` (report-only/smoke-test
    per `SLICE_CATALOG`, e.g. `kontak-kosmetik`, `masked-x-demografi`).
    Delta is still computed/reported when a baseline exists, but this
    NEVER blocks promotion.
  - `"pass_no_baseline"` - a critical slice with candidate data but no
    (or empty) baseline to compare against - typically the first-ever
    evaluation of that slice, or the very first promotion overall
    (mirrors `promote_model`'s own `is_first_promotion` carve-out for the
    overall-Recall gate). There is nothing to regress against, so this
    passes.
  - `"pass"` - critical slice, baseline present, regression (if any) is
    within tolerance (or the candidate is equal/better).
  - `"fail"` - critical slice, baseline present, regression exceeds
    tolerance. This is the only status that fails the overall gate.

`SliceRegressionGateReport.passes` is `True` iff no slice has status
`"fail"` - a candidate can carry any number of `"skipped_no_data"` /
`"report_only"` entries and still pass overall.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from ai_training.evaluation.e2e import SliceEvalSummary
from ai_training.evaluation.slices import SLICE_CATALOG
from ai_training.evaluation.stats import ci_width

MIN_DELTA_PP = 0.02  # 2 percentage points, TSD-EC D-7.3's floor tolerance.


class SliceRegressionResult(BaseModel):
    """Gate outcome for ONE slice (see module docstring for `status` values)."""

    slice_name: str
    status: str
    is_gate: bool
    candidate_recall: float | None = None
    candidate_total_genuine: int = 0
    baseline_recall: float | None = None
    baseline_total_genuine: int = 0
    delta: float | None = None  # baseline_recall - candidate_recall; positive == regression
    tolerance: float | None = None  # max(ci_width(candidate), MIN_DELTA_PP), only when checked
    reason: str = ""


class SliceRegressionGateReport(BaseModel):
    """Full EC-QA-01 gate result across every slice in `SLICE_CATALOG`."""

    passes: bool
    per_slice: dict[str, SliceRegressionResult]
    failed_slices: list[str]
    skipped_slices: list[str]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def evaluate_slice_regression_gate(
    candidate_slices: dict[str, SliceEvalSummary],
    baseline_slices: dict[str, SliceEvalSummary] | None,
    *,
    min_delta_pp: float = MIN_DELTA_PP,
) -> SliceRegressionGateReport:
    """EC-QA-01: evaluate the no-regression-bertoleransi-CI gate for every
    slice in `SLICE_CATALOG`.

    `candidate_slices`/`baseline_slices` map `slice_name -> SliceEvalSummary`
    (typically the `.e2e` or `.per_stage` summary from
    `ai_training.evaluation.e2e.evaluate_slice_e2e`, keyed by slice name -
    caller's choice which mode to gate on; TSD-EC D-7.5 wants both reported
    but does not mandate which one gates). `baseline_slices=None` (or a dict
    missing some slices) means "no promoted PRODUCTION model to compare
    against yet" - same first-promotion carve-out `promote_model` already
    has for the overall-Recall gate.

    Every slice not present (or with zero genuine probes) in
    `candidate_slices` is reported `"skipped_no_data"`, never silently
    dropped from `per_slice` - callers/tests can rely on `per_slice` always
    containing every `SLICE_CATALOG` key.
    """
    baseline_slices = baseline_slices or {}
    per_slice: dict[str, SliceRegressionResult] = {}

    for slice_name, spec in SLICE_CATALOG.items():
        candidate = candidate_slices.get(slice_name)
        baseline = baseline_slices.get(slice_name)
        candidate_has_data = candidate is not None and candidate.total_genuine > 0
        baseline_has_data = baseline is not None and baseline.total_genuine > 0

        if not candidate_has_data:
            per_slice[slice_name] = SliceRegressionResult(
                slice_name=slice_name,
                status="skipped_no_data",
                is_gate=spec.is_gate,
                reason=(
                    f"no candidate evaluation data for slice '{slice_name}' yet "
                    "(EC-OPS-02 real-subject collection pending, or slice not run "
                    "this evaluation) - skipped, not failed."
                ),
            )
            continue

        if not spec.is_gate:
            delta = (baseline.recall - candidate.recall) if baseline_has_data else None
            per_slice[slice_name] = SliceRegressionResult(
                slice_name=slice_name,
                status="report_only",
                is_gate=False,
                candidate_recall=candidate.recall,
                candidate_total_genuine=candidate.total_genuine,
                baseline_recall=baseline.recall if baseline_has_data else None,
                baseline_total_genuine=baseline.total_genuine if baseline_has_data else 0,
                delta=delta,
                reason=(
                    "report-only slice (smoke test or not yet gated per SLICE_CATALOG) - "
                    "never blocks promotion regardless of regression."
                ),
            )
            continue

        if not baseline_has_data:
            per_slice[slice_name] = SliceRegressionResult(
                slice_name=slice_name,
                status="pass_no_baseline",
                is_gate=True,
                candidate_recall=candidate.recall,
                candidate_total_genuine=candidate.total_genuine,
                reason="no PRODUCTION baseline for this slice yet - nothing to regress against.",
            )
            continue

        tolerance = max(ci_width(candidate.recall_ci), min_delta_pp)
        delta = baseline.recall - candidate.recall
        if delta > tolerance:
            status = "fail"
            reason = (
                f"Recall regressed {delta:.4f} on critical slice '{slice_name}' "
                f"(candidate {candidate.recall:.4f} vs baseline {baseline.recall:.4f}), "
                f"exceeding tolerance {tolerance:.4f} = max(CI width, {min_delta_pp})."
            )
        else:
            status = "pass"
            reason = (
                f"Recall delta {delta:.4f} on critical slice '{slice_name}' is within "
                f"tolerance {tolerance:.4f} = max(CI width, {min_delta_pp})."
            )

        per_slice[slice_name] = SliceRegressionResult(
            slice_name=slice_name,
            status=status,
            is_gate=True,
            candidate_recall=candidate.recall,
            candidate_total_genuine=candidate.total_genuine,
            baseline_recall=baseline.recall,
            baseline_total_genuine=baseline.total_genuine,
            delta=delta,
            tolerance=tolerance,
            reason=reason,
        )

    failed_slices = [name for name, r in per_slice.items() if r.status == "fail"]
    skipped_slices = [name for name, r in per_slice.items() if r.status == "skipped_no_data"]

    return SliceRegressionGateReport(
        passes=not failed_slices,
        per_slice=per_slice,
        failed_slices=failed_slices,
        skipped_slices=skipped_slices,
    )
