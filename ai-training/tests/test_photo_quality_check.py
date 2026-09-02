"""`run_photo_quality_check` — the per-clock-position photo path that
replaced `rotation.webm` (FR-ENR-02, backend migration `e4b9d2f6a8c3`).

Heavy pieces (cv2 decode, mediapipe landmarks, solvePnP) are monkeypatched:
these tests are about the PHOTO-SPECIFIC logic — that a frame is judged
against the position it was captured for, that unusable frames cost only
themselves, and that the verdict is folded exactly as the video path folds
it — not about re-testing the estimators.
"""

from __future__ import annotations

from typing import Any

import pytest

from ai_training.config import QCSettings
from ai_training.quality import pipeline as qc_pipeline
from ai_training.quality.pipeline import run_photo_quality_check


@pytest.fixture
def settings() -> QCSettings:
    return QCSettings()


def _photo(position: str) -> tuple[str, bytes]:
    return position, f"bytes-{position}".encode()


def _all_twelve() -> list[tuple[str, bytes]]:
    return [_photo(f"{i:02d}") for i in range(1, 13)]


@pytest.fixture
def stub_frames(monkeypatch):
    """Make decoding a no-op and every frame pass, so a test only has to
    override the bit it cares about."""
    monkeypatch.setattr(qc_pipeline, "decode_image", lambda data: {"data": data})

    def fake_evaluate(frame, settings, neutral_pose=None, declared_position=None):
        return _FakeQuality(position=declared_position or "12", passed=True)

    monkeypatch.setattr(qc_pipeline, "_evaluate_frame", fake_evaluate)


class _FakeQuality:
    def __init__(self, *, position: str, passed: bool, reasons: list[str] | None = None) -> None:
        self.position = position
        self.passed = passed
        self.reasons = reasons or []
        self.blur = 120.0


def test_full_coverage_passes(settings, stub_frames) -> None:
    report, by_position = run_photo_quality_check(
        _all_twelve(), session_id="s1", settings=settings
    )

    assert report.overall == "PASS"
    assert report.coverage_ratio == 1.0
    assert sorted(by_position) == [f"{i:02d}" for i in range(1, 13)]


def test_each_frame_is_scored_against_the_position_it_was_captured_for(
    settings, monkeypatch
) -> None:
    """The whole reason `clock_position` exists on the row. On the video
    path a frame is filed under whichever target it lands NEAREST, so pose
    drift silently re-labels it; here it must be filed under its declared
    position so the drift shows up as that position's failure."""
    monkeypatch.setattr(qc_pipeline, "decode_image", lambda data: {"data": data})
    seen: list[str | None] = []

    def fake_evaluate(frame, settings, neutral_pose=None, declared_position=None):
        seen.append(declared_position)
        return _FakeQuality(position=declared_position or "12", passed=True)

    monkeypatch.setattr(qc_pipeline, "_evaluate_frame", fake_evaluate)

    run_photo_quality_check([_photo("05"), _photo("09")], session_id="s1", settings=settings)

    assert seen == ["05", "09"]


def test_a_burst_of_several_frames_for_one_position_is_normal(settings, stub_frames) -> None:
    photos = [*_all_twelve(), ("05", b"extra-a"), ("05", b"extra-b")]

    report, by_position = run_photo_quality_check(photos, session_id="s1", settings=settings)

    assert len(by_position["05"]) == 3
    assert report.overall == "PASS"


def test_a_position_passes_when_any_one_of_its_burst_frames_passes(
    settings, monkeypatch
) -> None:
    """The point of capturing a burst: one blurry frame in the burst must
    not sink the position when a sharp one is sitting right next to it."""
    monkeypatch.setattr(qc_pipeline, "decode_image", lambda data: {"data": data})

    def fake_evaluate(frame, settings, neutral_pose=None, declared_position=None):
        blurry = frame["data"].endswith(b"-bad")
        return _FakeQuality(
            position=declared_position or "12",
            passed=not blurry,
            reasons=["blurry"] if blurry else [],
        )

    monkeypatch.setattr(qc_pipeline, "_evaluate_frame", fake_evaluate)

    photos = [*_all_twelve(), ("05", b"bytes-05-bad")]
    report, _ = run_photo_quality_check(photos, session_id="s1", settings=settings)

    position_05 = next(p for p in report.positions if p.position == "05")
    assert position_05.passed is True
    assert report.overall == "PASS"


def test_an_uncovered_position_reports_no_face_detected(settings, stub_frames) -> None:
    photos = [p for p in _all_twelve() if p[0] != "07"]

    report, _ = run_photo_quality_check(photos, session_id="s1", settings=settings)

    position_07 = next(p for p in report.positions if p.position == "07")
    assert position_07.passed is False
    assert position_07.reasons == ["no_face_detected"]


def test_partial_coverage_below_min_pass_ratio_is_rejected(settings, stub_frames) -> None:
    # 6/12 = 0.5, under the 0.75 default.
    report, _ = run_photo_quality_check(
        _all_twelve()[:6], session_id="s1", settings=settings
    )

    assert report.overall == "REJECTED_QUALITY"
    assert report.coverage_ratio == pytest.approx(0.5)


def test_coverage_at_the_min_pass_ratio_passes(settings, stub_frames) -> None:
    # 9/12 = 0.75 exactly -- the boundary the video path also uses, so the
    # two capture shapes are held to identical standards.
    report, _ = run_photo_quality_check(
        _all_twelve()[:9], session_id="s1", settings=settings
    )

    assert report.overall == "PASS"
    assert report.coverage_ratio == pytest.approx(0.75)


def test_an_undecodable_frame_costs_only_that_frame(settings, monkeypatch) -> None:
    """A corrupt JPEG must not raise: it drops out and its position falls
    back on its remaining candidates, exactly like a frame with no face."""

    def fake_decode(data: bytes) -> Any:
        return None if data == b"corrupt" else {"data": data}

    monkeypatch.setattr(qc_pipeline, "decode_image", fake_decode)
    monkeypatch.setattr(
        qc_pipeline,
        "_evaluate_frame",
        lambda frame, settings, neutral_pose=None, declared_position=None: _FakeQuality(
            position=declared_position or "12", passed=True
        ),
    )

    photos = [*_all_twelve(), ("05", b"corrupt")]
    report, by_position = run_photo_quality_check(photos, session_id="s1", settings=settings)

    assert report.overall == "PASS"
    assert len(by_position["05"]) == 1


def test_every_frame_being_undecodable_rejects_rather_than_raising(
    settings, monkeypatch
) -> None:
    monkeypatch.setattr(qc_pipeline, "decode_image", lambda data: None)

    report, by_position = run_photo_quality_check(
        _all_twelve(), session_id="s1", settings=settings
    )

    assert report.overall == "REJECTED_QUALITY"
    assert report.coverage_ratio == 0.0
    assert all(not frames for frames in by_position.values())


def test_a_frame_with_no_face_is_dropped(settings, monkeypatch) -> None:
    monkeypatch.setattr(qc_pipeline, "decode_image", lambda data: {"data": data})
    monkeypatch.setattr(
        qc_pipeline,
        "_evaluate_frame",
        lambda frame, settings, neutral_pose=None, declared_position=None: None,
    )

    report, by_position = run_photo_quality_check(
        _all_twelve(), session_id="s1", settings=settings
    )

    assert report.overall == "REJECTED_QUALITY"
    assert by_position["01"] == []


def test_an_out_of_range_position_label_is_ignored_not_fatal(settings, stub_frames) -> None:
    """Defence in depth: the backend already rejects clock_position outside
    1..12 at presign, so a "13" here would mean corrupt data — drop it
    rather than KeyError the whole session."""
    photos = [*_all_twelve(), ("13", b"nonsense"), ("00", b"nonsense")]

    report, by_position = run_photo_quality_check(photos, session_id="s1", settings=settings)

    assert report.overall == "PASS"
    assert "13" not in by_position
    assert "00" not in by_position


def test_neutral_pose_is_forwarded_to_every_frame(settings, monkeypatch) -> None:
    monkeypatch.setattr(qc_pipeline, "decode_image", lambda data: {"data": data})
    seen: list[tuple[float, float] | None] = []

    def fake_evaluate(frame, settings, neutral_pose=None, declared_position=None):
        seen.append(neutral_pose)
        return _FakeQuality(position=declared_position or "12", passed=True)

    monkeypatch.setattr(qc_pipeline, "_evaluate_frame", fake_evaluate)

    run_photo_quality_check(
        _all_twelve(), session_id="s1", settings=settings, neutral_pose=(1.0, 24.0)
    )

    assert seen == [(1.0, 24.0)] * 12


def test_no_photos_at_all_rejects_with_full_position_breakdown(settings, stub_frames) -> None:
    report, _ = run_photo_quality_check([], session_id="s1", settings=settings)

    assert report.overall == "REJECTED_QUALITY"
    assert report.coverage_ratio == 0.0
    # Still reports all 12, so the operator sees what is missing rather
    # than an empty list.
    assert len(report.positions) == 12
