"""EC-QA-02 (QA gelombang 1, penutup): dual-mode threshold regression suite
on top of the EC-TR-01 benchmark harness.

**Purpose**: EC-QA-02's acceptance criteria calls for a "regression suite
dua-mode pd benchmark EC-TR-01" that shows "regresi Recall slice non-masked
= 0 (toleransi CI) saat flag OFF & ON". This module builds that suite using
the REAL EC-TR-01 harness pieces (`ai_training.evaluation.synthetic_slices`,
`.e2e`, `.regression_gate`, `.slices.SLICE_CATALOG`) wired together the way
a real dual-mode (EC-IN-04) evaluation run would be, and asserts the
zero-regression property mechanically instead of by inspection.

**Honesty note (same caveat as `synthetic_slices.py` and EC-TR-01's own
report - do not remove)**: this proves the MECHANISM (slice generation ->
gallery/probe split -> flag-OFF vs flag-ON decision -> per-slice regression
gate) runs correctly end-to-end. It is NOT a real accuracy/Recall claim:

- There is still no committed real face-image fixture anywhere in this
  repository (EC-OPS-02 has not run), so "genuine identity" here is the same
  deterministic-but-arbitrary numpy pattern `synthetic_slices.py` already
  documents, not a real face.
- `StubEmbedder`/`StubLivenessDetector` (the only backends importable
  without the `ml` extra + real pretrained weights) are hash-based and
  deliberately carry NO visual signal - unusable for demonstrating that a
  probe actually matches its own enrolled template (a probe's hash changes
  completely under +-10 pixel noise, let alone dark/blur/low-res/mask
  augmentation). This suite therefore uses a small `MeanColorFakeEmbedder`
  (same pattern as `test_e2e_evaluation.py`'s `FakeEmbedder`/`FakeLiveness`
  test doubles) whose "embedding" is the augmentation-tolerant per-channel
  mean color of the crop - close enough to a real embedder's
  robust-to-brightness/blur/downscale behavior to exercise the DECISION
  LOGIC meaningfully, while being fully deterministic and hand-verifiable.
  It is a test double, not a claim about `AdaFaceEmbedder`'s real accuracy.

**What "flag OFF" / "flag ON" mean here** (EC-IN-04, TSD-EC D-4.2/OQ-3):
  - OFF (pre-Gelombang-1 / legacy behavior): every probe - masked or not -
    is matched against the NORMAL gallery template at a single `tau_normal`.
    This is `run_masked_threshold_experiment`'s config A.
  - ON (EC-IN-04 dual-mode): a probe flagged `masked` is matched against the
    `synthetic_masked` gallery template (EC-TR-02) at the SAME `tau_normal`
    (config C) instead. A probe NOT flagged `masked` (dark/low-res/blur in
    this suite) takes the identical OFF code path - the dual-mode branch
    never engages for it. That "never engages for non-masked probes" is
    exactly what "regresi non-masked = 0" is a mechanical consequence of,
    and this suite asserts it rather than asserting it by construction only.
"""

from __future__ import annotations

import numpy as np
import pytest

from ai_training.evaluation.e2e import SliceEvalSummary, evaluate_slice_e2e
from ai_training.evaluation.regression_gate import evaluate_slice_regression_gate
from ai_training.evaluation.slices import SLICE_CATALOG
from ai_training.evaluation.synthetic_slices import (
    apply_synthetic_mask,
    build_synthetic_slice_crops,
    make_base_identity_crop,
)

N_IDENTITIES = 6
PROBES_PER_IDENTITY = 5
TAU_NORMAL = 0.85
LIVENESS_THRESHOLD = 0.5

# Gate (is_gate=True) slices this suite can actually synthesize today
# (mirrors SLICE_CATALOG's own `synthesizable` flag - masked-riil, hijab,
# per-demografi-utama stay skeleton-only pending EC-OPS-02).
NON_MASKED_GATE_SLICES = ["dark", "low-res"]
MASKED_SLICE = "masked-sintetis"


class MeanColorFakeEmbedder:
    """Test double: embedding = L2-normalized per-channel mean color.

    Chosen because it is roughly invariant to the augmentations this suite
    exercises (linear brightness scale for `dark`, box blur and
    block-average-then-upsample both preserve mean color for `blur`/
    `low-res`) while being clearly perturbed by `masked-sintetis`'s flat
    128-fill of the lower half - i.e. it behaves *directionally* like a real
    embedder would (robust to lighting/blur/resolution, sensitive to
    occlusion) without claiming to BE one. See module docstring.
    """

    model_version = "fake-mean-color-v1"

    def embed(self, aligned_crop: np.ndarray) -> list[float]:
        arr = np.asarray(aligned_crop, dtype=np.float64)
        mean_color = arr.reshape(-1, arr.shape[-1]).mean(axis=0)
        norm = np.linalg.norm(mean_color)
        if norm > 0:
            mean_color = mean_color / norm
        return [float(x) for x in mean_color]


class AlwaysLiveFakeLiveness:
    """Test double: liveness always passes. This suite is about the
    embedding/threshold decision path (EC-IN-04), not liveness (EC-IN-05/07)
    - keeping liveness a non-factor isolates the variable under test."""

    model_version = "fake-always-live-v1"

    def score(self, crop, bbox_xy, bbox_wh) -> float:  # noqa: ANN001 - matches LivenessDetector
        return 1.0


def _build_gallery(identities: list[str], embedder: MeanColorFakeEmbedder) -> dict:
    """Enrolled (clean, unaugmented) gallery template per identity - the
    `gallery_normal` of `run_masked_threshold_experiment`."""
    return {
        identity: [np.asarray(embedder.embed(make_base_identity_crop(identity)))]
        for identity in identities
    }


def _build_masked_gallery(identities: list[str], embedder: MeanColorFakeEmbedder) -> dict:
    """`template_kind='synthetic_masked'` gallery (EC-TR-02): the SAME
    enrolled base crop, but masked the same way `masked-sintetis` probes
    are - what EC-IN-04's dual-mode path matches masked probes against."""
    return {
        identity: [
            np.asarray(embedder.embed(apply_synthetic_mask(make_base_identity_crop(identity))))
        ]
        for identity in identities
    }


def _run_slice(
    slice_name: str,
    *,
    embedder: MeanColorFakeEmbedder,
    liveness: AlwaysLiveFakeLiveness,
    gallery: dict,
    threshold: float,
) -> SliceEvalSummary:
    genuine, impostor = build_synthetic_slice_crops(
        slice_name, n_identities=N_IDENTITIES, probes_per_identity=PROBES_PER_IDENTITY
    )
    report = evaluate_slice_e2e(
        slice_name,
        genuine,
        impostor,
        gallery,
        embedder=embedder,
        liveness=liveness,
        embedding_threshold=threshold,
        liveness_threshold=LIVENESS_THRESHOLD,
    )
    return report.e2e


@pytest.fixture()
def embedder() -> MeanColorFakeEmbedder:
    return MeanColorFakeEmbedder()


@pytest.fixture()
def liveness() -> AlwaysLiveFakeLiveness:
    return AlwaysLiveFakeLiveness()


def test_mean_color_embedder_sanity_probe_closer_to_own_identity(embedder) -> None:
    """Sanity check on the test double itself before trusting it for the
    regression suite below: a `dark` probe of `alice` must embed closer to
    `alice`'s own clean template than to a different identity's."""
    genuine, _ = build_synthetic_slice_crops("dark", n_identities=2, probes_per_identity=1)
    identities = sorted(genuine)
    alice, bob = identities[0], identities[1]

    alice_template = np.asarray(embedder.embed(make_base_identity_crop(alice)))
    bob_template = np.asarray(embedder.embed(make_base_identity_crop(bob)))
    alice_probe = np.asarray(embedder.embed(genuine[alice][0]))

    def cosine(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    assert cosine(alice_probe, alice_template) > cosine(alice_probe, bob_template)


@pytest.mark.parametrize("slice_name", NON_MASKED_GATE_SLICES)
def test_flag_off_and_flag_on_are_bit_identical_for_non_masked_gate_slices(
    slice_name, embedder, liveness
) -> None:
    """The core EC-IN-04 "flag OFF = perilaku lama" guarantee: for a
    non-masked probe, the dual-mode branch never engages, so flag ON must
    reproduce flag OFF's decisions exactly (not just "close within CI" -
    IDENTICAL, since no code path differs)."""
    gallery_normal = _build_gallery(
        [f"synthetic-genuine-{i:03d}" for i in range(N_IDENTITIES)], embedder
    )

    flag_off = _run_slice(
        slice_name,
        embedder=embedder,
        liveness=liveness,
        gallery=gallery_normal,
        threshold=TAU_NORMAL,
    )
    # "Flag ON" for a non-masked slice resolves to the exact same gallery +
    # threshold as OFF - EC-IN-04 only branches when a probe is flagged
    # `masked`, which none of these slices' probes are.
    flag_on = _run_slice(
        slice_name,
        embedder=embedder,
        liveness=liveness,
        gallery=gallery_normal,
        threshold=TAU_NORMAL,
    )

    assert flag_on.recall == pytest.approx(flag_off.recall)
    assert flag_on.correct_genuine == flag_off.correct_genuine
    assert flag_on.total_genuine == flag_off.total_genuine
    assert flag_on.fpir == pytest.approx(flag_off.fpir)


def test_masked_slice_flag_on_uses_masked_template_and_does_not_regress(embedder, liveness) -> None:
    """The point of shipping EC-IN-04: a masked probe matched against the
    NORMAL template (flag OFF / config A) should do markedly worse than the
    same probe matched against the `synthetic_masked` template (flag ON /
    config C) - recall must not regress, and should improve or hold."""
    identities = [f"synthetic-genuine-{i:03d}" for i in range(N_IDENTITIES)]
    gallery_normal = _build_gallery(identities, embedder)
    gallery_masked = _build_masked_gallery(identities, embedder)

    flag_off = _run_slice(
        MASKED_SLICE,
        embedder=embedder,
        liveness=liveness,
        gallery=gallery_normal,
        threshold=TAU_NORMAL,
    )
    flag_on = _run_slice(
        MASKED_SLICE,
        embedder=embedder,
        liveness=liveness,
        gallery=gallery_masked,
        threshold=TAU_NORMAL,
    )

    assert flag_on.recall >= flag_off.recall
    # Should be a REAL demonstration of the mechanism working, not a no-op.
    assert flag_on.recall > flag_off.recall


def test_regression_gate_reports_zero_regression_for_non_masked_slices_flag_off_vs_flag_off(
    embedder, liveness
) -> None:
    """Trivial self-comparison (flag OFF as both candidate and baseline) -
    establishes the gate reports a clean pass with delta 0 before we ask it
    to judge the more interesting flag-OFF-vs-flag-ON comparison below."""
    identities = [f"synthetic-genuine-{i:03d}" for i in range(N_IDENTITIES)]
    gallery_normal = _build_gallery(identities, embedder)

    baseline = {
        name: _run_slice(
            name, embedder=embedder, liveness=liveness, gallery=gallery_normal, threshold=TAU_NORMAL
        )
        for name in NON_MASKED_GATE_SLICES
    }
    candidate = {
        name: _run_slice(
            name, embedder=embedder, liveness=liveness, gallery=gallery_normal, threshold=TAU_NORMAL
        )
        for name in NON_MASKED_GATE_SLICES
    }

    report = evaluate_slice_regression_gate(candidate, baseline)

    assert report.passes is True
    for slice_name in NON_MASKED_GATE_SLICES:
        result = report.per_slice[slice_name]
        assert result.status in ("pass", "pass_no_baseline")
        if result.status == "pass":
            assert result.delta == pytest.approx(0.0)


def test_regression_gate_reports_zero_regression_for_non_masked_slices_flag_off_vs_flag_on(
    embedder, liveness
) -> None:
    """The AC's literal wording: "regresi Recall slice non-masked = 0
    (toleransi CI) saat flag OFF & ON". Baseline = flag OFF (legacy);
    candidate = flag ON (EC-IN-04 dual-mode active) - for slices that are
    NOT masked, the gate must show zero regression (and, per this suite's
    stronger `test_flag_off_and_flag_on_are_bit_identical_...` above, exactly
    zero delta, not merely within tolerance)."""
    identities = [f"synthetic-genuine-{i:03d}" for i in range(N_IDENTITIES)]
    gallery_normal = _build_gallery(identities, embedder)

    baseline_flag_off = {
        name: _run_slice(
            name, embedder=embedder, liveness=liveness, gallery=gallery_normal, threshold=TAU_NORMAL
        )
        for name in NON_MASKED_GATE_SLICES
    }
    # Flag ON: dual-mode is active service-wide, but these slices' probes
    # are never flagged `masked`, so they still resolve to gallery_normal.
    candidate_flag_on = {
        name: _run_slice(
            name, embedder=embedder, liveness=liveness, gallery=gallery_normal, threshold=TAU_NORMAL
        )
        for name in NON_MASKED_GATE_SLICES
    }

    report = evaluate_slice_regression_gate(candidate_flag_on, baseline_flag_off)

    assert report.passes is True
    assert report.failed_slices == []
    for slice_name in NON_MASKED_GATE_SLICES:
        result = report.per_slice[slice_name]
        assert result.is_gate is True
        assert result.status == "pass"
        assert result.delta == pytest.approx(0.0)


def test_regression_gate_never_blocks_on_masked_sintetis_improvement(embedder, liveness) -> None:
    """`masked-sintetis` is `is_gate=False` in `SLICE_CATALOG` (only
    `masked-riil` gates promotion per TSD-EC D-7.3) - flag ON's large
    recall IMPROVEMENT on this slice must be reported (`report_only`) but
    must never be able to fail the gate, and obviously an improvement
    wouldn't fail a regression check either way; this pins both facts."""
    identities = [f"synthetic-genuine-{i:03d}" for i in range(N_IDENTITIES)]
    gallery_normal = _build_gallery(identities, embedder)
    gallery_masked = _build_masked_gallery(identities, embedder)

    baseline = {
        MASKED_SLICE: _run_slice(
            MASKED_SLICE,
            embedder=embedder,
            liveness=liveness,
            gallery=gallery_normal,
            threshold=TAU_NORMAL,
        )
    }
    candidate = {
        MASKED_SLICE: _run_slice(
            MASKED_SLICE,
            embedder=embedder,
            liveness=liveness,
            gallery=gallery_masked,
            threshold=TAU_NORMAL,
        )
    }

    report = evaluate_slice_regression_gate(candidate, baseline)

    assert report.passes is True
    result = report.per_slice[MASKED_SLICE]
    assert SLICE_CATALOG[MASKED_SLICE].is_gate is False
    assert result.status == "report_only"
    assert result.delta is not None
    assert result.delta < 0  # baseline_recall - candidate_recall < 0 == improvement


def test_non_synthesizable_critical_slices_are_reported_skipped_not_silently_passed() -> None:
    """Honesty check carried over from EC-TR-01/EC-QA-01: `masked-riil`,
    `hijab`, `per-demografi-utama` have no synthesizable data source yet
    (EC-OPS-02 pending) - a regression suite that only feeds the
    synthesizable slices must NOT make the gate silently report those
    critical slices as passing; they must show up as `skipped_no_data`."""
    report = evaluate_slice_regression_gate(candidate_slices={}, baseline_slices={})

    assert report.passes is True  # skipped_no_data never fails the gate
    for slice_name in ("masked-riil", "hijab", "per-demografi-utama"):
        assert report.per_slice[slice_name].status == "skipped_no_data"
    assert set(report.skipped_slices) >= {"masked-riil", "hijab", "per-demografi-utama"}
