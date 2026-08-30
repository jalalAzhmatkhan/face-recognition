"""TR-05 EDA report aggregation, with `load_snapshot`/`run_quality_check`
patched out so this never touches real S3 or needs the `ml` extra
(cv2/mediapipe) - per task instructions, only synthetic per-video quality
results are used, matching the "aggregation tested in isolation" allowance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

import ai_training.eda.report as eda_report_module
from ai_training.config import Settings
from ai_training.data.snapshots import DatasetSnapshot, MediaEntry
from ai_training.eda.report import (
    EDAReport,
    PositionCoverage,
    ScoreStats,
    build_eda_report,
    render_markdown,
)
from ai_training.quality.pipeline import FrameQuality
from ai_training.quality.pose import CLOCK_POSITIONS
from ai_training.quality.report import PositionResult, QCReport


def _settings() -> Settings:
    return Settings(_env_file=None)


def _qc_report(session_id: str, overall: str, passing_positions: list[str]) -> QCReport:
    positions = [
        PositionResult(
            position=p,
            passed=p in passing_positions,
            reasons=[] if p in passing_positions else ["no_face_detected"],
        )
        for p in CLOCK_POSITIONS
    ]
    return QCReport(
        session_id=session_id,
        overall=overall,
        coverage_ratio=len(passing_positions) / len(CLOCK_POSITIONS),
        positions=positions,
        generated_at=datetime.now(UTC),
    )


def _frames_by_position(
    blur_by_position: dict[str, float], brightness_by_position: dict[str, float]
) -> dict[str, list[FrameQuality]]:
    frames: dict[str, list[FrameQuality]] = {p: [] for p in CLOCK_POSITIONS}
    for position, blur in blur_by_position.items():
        frames[position].append(
            FrameQuality(
                frame=None,
                position=position,
                blur=blur,
                brightness=brightness_by_position[position],
                face_ratio=0.5,
                yaw=0.0,
                pitch=0.0,
                passed=True,
                reasons=[],
            )
        )
    return frames


def _manifest() -> DatasetSnapshot:
    return DatasetSnapshot(
        snapshot_id="snap-1",
        media_keys=["k1", "k2", "k2b", "k3"],
        media=[
            MediaEntry(s3_key="k1", kind="video", user_id="u1", session_id="s1"),
            MediaEntry(s3_key="k2", kind="video", user_id="u1", session_id="s2"),
            MediaEntry(s3_key="k2b", kind="photo", user_id="u1", session_id="s2"),
            MediaEntry(s3_key="k3", kind="video", user_id="u2", session_id="s3"),
        ],
        media_bucket="frac-media",
        user_ids=["u1", "u2"],
        session_ids=["s1", "s2", "s3"],
        total_media_count=4,
    )


def _fake_run_quality_check(video_bytes, *, session_id, settings):
    if session_id == "s1":
        return (
            _qc_report("s1", "PASS", ["01", "02"]),
            _frames_by_position({"01": 100.0, "02": 120.0}, {"01": 150.0, "02": 160.0}),
        )
    if session_id == "s2":
        return _qc_report("s2", "REJECTED_QUALITY", []), _frames_by_position({}, {})
    if session_id == "s3":
        raise RuntimeError("corrupt video, undecodable")
    raise AssertionError(f"unexpected session_id {session_id}")


def test_build_eda_report_aggregates_pass_fail_and_undecodable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    monkeypatch.setattr(eda_report_module, "load_snapshot", lambda *a, **k: manifest)
    monkeypatch.setattr(eda_report_module, "run_quality_check", _fake_run_quality_check)

    s3 = MagicMock()
    report = build_eda_report(
        _settings(),
        "snap-1",
        s3_client=s3,
        downloader=lambda bucket, key, client: b"fake-video-bytes",
    )

    assert report.total_videos == 3  # k1, k2, k3 -- k2b is a photo, excluded
    assert report.videos_qc_passed == 1
    assert report.videos_qc_failed == 1
    assert report.videos_undecodable == 1
    assert report.qc_pass_ratio == pytest.approx(0.5)  # 1 pass / (1 pass + 1 fail)
    assert report.unique_users == 2
    assert report.unique_sessions == 3
    assert report.videos_per_user == {"u1": 2, "u2": 1}


def test_build_eda_report_coverage_by_clock_position(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest()
    monkeypatch.setattr(eda_report_module, "load_snapshot", lambda *a, **k: manifest)
    monkeypatch.setattr(eda_report_module, "run_quality_check", _fake_run_quality_check)

    report = build_eda_report(
        _settings(),
        "snap-1",
        s3_client=MagicMock(),
        downloader=lambda bucket, key, client: b"fake-video-bytes",
    )

    coverage = {c.position: c for c in report.coverage_by_position}
    assert coverage["01"].videos_with_pass == 1
    assert coverage["01"].total_videos_scored == 2  # s1 (pass) + s2 (fail) were scored
    assert coverage["12"].videos_with_pass == 0


def test_build_eda_report_blur_and_brightness_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest()
    monkeypatch.setattr(eda_report_module, "load_snapshot", lambda *a, **k: manifest)
    monkeypatch.setattr(eda_report_module, "run_quality_check", _fake_run_quality_check)

    report = build_eda_report(
        _settings(),
        "snap-1",
        s3_client=MagicMock(),
        downloader=lambda bucket, key, client: b"fake-video-bytes",
    )

    # Only s1 contributed frames (s2 had none, s3 raised before decoding).
    assert report.blur_score_stats.count == 2
    assert report.blur_score_stats.mean == pytest.approx(110.0)
    assert report.brightness_score_stats.count == 2
    assert report.brightness_score_stats.mean == pytest.approx(155.0)


def test_build_eda_report_download_failure_counts_as_undecodable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = DatasetSnapshot(
        snapshot_id="snap-2",
        media_keys=["k1"],
        media=[MediaEntry(s3_key="k1", kind="video", user_id="u1", session_id="s1")],
        media_bucket="frac-media",
        user_ids=["u1"],
        session_ids=["s1"],
        total_media_count=1,
    )
    monkeypatch.setattr(eda_report_module, "load_snapshot", lambda *a, **k: manifest)

    def _boom(bucket, key, client):
        raise ConnectionError("s3 unreachable")

    report = build_eda_report(
        _settings(), "snap-2", s3_client=MagicMock(), downloader=_boom
    )

    assert report.total_videos == 1
    assert report.videos_undecodable == 1
    assert report.videos_qc_passed == 0
    assert report.videos_qc_failed == 0


def test_build_eda_report_uploads_json_and_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest()
    monkeypatch.setattr(eda_report_module, "load_snapshot", lambda *a, **k: manifest)
    monkeypatch.setattr(eda_report_module, "run_quality_check", _fake_run_quality_check)

    s3 = MagicMock()
    settings = _settings()
    build_eda_report(
        settings,
        "snap-1",
        s3_client=s3,
        downloader=lambda bucket, key, client: b"fake-video-bytes",
    )

    assert s3.put_object.call_count == 2
    keys = {call.kwargs["Key"] for call in s3.put_object.call_args_list}
    assert keys == {"datasets/snap-1/eda_report.json", "datasets/snap-1/eda_report.md"}
    for call in s3.put_object.call_args_list:
        assert call.kwargs["Bucket"] == settings.s3.bucket


def test_render_markdown_contains_key_sections() -> None:
    report = EDAReport(
        snapshot_id="snap-1",
        total_videos=3,
        videos_qc_passed=1,
        videos_qc_failed=1,
        videos_undecodable=1,
        qc_pass_ratio=0.5,
        unique_users=2,
        unique_sessions=3,
        videos_per_user={"u1": 2, "u2": 1},
        coverage_by_position=[
            PositionCoverage(position="01", videos_with_pass=1, total_videos_scored=2)
        ],
        blur_score_stats=ScoreStats(count=2, min=100.0, max=120.0, mean=110.0, stdev=10.0),
        brightness_score_stats=ScoreStats(),
    )
    markdown = render_markdown(report)

    assert "# EDA report - snapshot `snap-1`" in markdown
    assert "| u1 | 2 |" in markdown
    assert "| 01 | 1 | 2 |" in markdown
    assert "Blur score" in markdown
    assert "Brightness score" in markdown
