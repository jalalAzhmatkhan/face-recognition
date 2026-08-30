"""EDA report builder for a dataset snapshot (TR-05, FR-TRN-01/03).

**Module location**: a new top-level package (`ai_training.eda`) rather
than folding this into `ai_training.data` or `ai_training.quality` -
turning a TR-04 manifest into an aggregate report is a distinct pipeline
stage from either "list the media" (`data.snapshots`) or "score one
video/frame" (`quality.*`); it *consumes* both. Mirrors how `embedding/`,
`training/`, `evaluation/` are each their own package for one stage.

**Approach chosen: re-run the QC pipeline per video** (`extract_frames` +
`run_quality_check`, both reused unmodified from TR-02 -
`ai_training.quality.pipeline`) rather than reading the historical
`qc_report` already stored on `enrollment_sessions` by the TR-02 worker.

Trade-off (documented per task instructions):
  - **Re-run (chosen)**: every video in the report is scored against the
    SAME, *current* `QCSettings` thresholds, so the aggregate distribution
    (coverage per clock position, blur/brightness stats, pass ratio) is
    apples-to-apples across the whole dataset even if a session enrolled
    months ago under different threshold tuning (`config.py` documents
    `QCSettings` as still-being-calibrated placeholders). Cost: slower -
    every video is re-downloaded from S3 and re-decoded, no caching of the
    stored `qc_report`. Acceptable because this is an offline dataset-prep
    report, not a latency-sensitive path.
  - **Reading stored `qc_report`** (rejected): much cheaper (no S3 traffic,
    no video decode), but "representative of the dataset" quietly erodes
    over time as thresholds are retuned - an EDA report built today would
    partly describe "how the pipeline scored things back when it was
    tuned differently", which defeats the point of an EDA report meant to
    inform *current* training-data quality decisions.

Media-at-rest rule (NFR-SEC-02): video bytes are downloaded straight into
memory and handed to `extract_frames` (which itself uses a short-lived
temp file it deletes immediately, documented in `quality.pipeline`) - this
module never writes anything to permanent local disk.
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from ai_training.config import Settings
from ai_training.data.snapshots import load_snapshot
from ai_training.quality.pipeline import run_quality_check
from ai_training.quality.pose import CLOCK_POSITIONS
from ai_training.storage import build_s3_client

VIDEO_KIND = "video"


class PositionCoverage(BaseModel):
    """How many videos had >=1 passing frame at this clock position."""

    position: str
    videos_with_pass: int
    total_videos_scored: int


class ScoreStats(BaseModel):
    count: int = 0
    min: float = 0.0
    max: float = 0.0
    mean: float = 0.0
    stdev: float = 0.0


class EDAReport(BaseModel):
    snapshot_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    total_videos: int = 0
    videos_qc_passed: int = 0
    videos_qc_failed: int = 0
    videos_undecodable: int = 0
    qc_pass_ratio: float = 0.0
    unique_users: int = 0
    unique_sessions: int = 0
    videos_per_user: dict[str, int] = Field(default_factory=dict)
    coverage_by_position: list[PositionCoverage] = Field(default_factory=list)
    blur_score_stats: ScoreStats = Field(default_factory=ScoreStats)
    brightness_score_stats: ScoreStats = Field(default_factory=ScoreStats)


def _score_stats(values: list[float]) -> ScoreStats:
    if not values:
        return ScoreStats()
    return ScoreStats(
        count=len(values),
        min=float(min(values)),
        max=float(max(values)),
        mean=float(statistics.fmean(values)),
        stdev=float(statistics.pstdev(values)) if len(values) > 1 else 0.0,
    )


def _default_downloader(bucket: str, key: str, s3_client: Any) -> bytes:
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def build_eda_report(
    settings: Settings,
    snapshot_id: str,
    *,
    s3_client: Any = None,
    downloader: Any = _default_downloader,
) -> EDAReport:
    """Build the EDA report for `snapshot_id`, then upload it to
    ``datasets/{snapshot_id}/eda_report.json`` and
    ``datasets/{snapshot_id}/eda_report.md`` in `settings.s3.bucket`.

    Iterates every ``kind == "video"`` entry in the snapshot manifest,
    downloads it into memory, and reuses TR-02's `run_quality_check`
    unmodified. A video that fails to decode (`RuntimeError` from
    `extract_frames`, e.g. corrupt upload) is counted in
    `videos_undecodable` rather than aborting the whole report, mirroring
    `worker.tasks.run_enrollment_qc_core`'s handling of the same error.
    """
    client = s3_client if s3_client is not None else build_s3_client(settings)
    manifest = load_snapshot(settings, snapshot_id, s3_client=client)

    videos = [entry for entry in manifest.media if entry.kind == VIDEO_KIND]

    blur_values: list[float] = []
    brightness_values: list[float] = []
    passed = 0
    failed = 0
    undecodable = 0
    position_pass_counts: Counter[str] = Counter()
    videos_per_user: Counter[str] = Counter()

    for entry in videos:
        videos_per_user[entry.user_id] += 1
        try:
            video_bytes = downloader(manifest.media_bucket, entry.s3_key, client)
        except Exception:  # noqa: BLE001 - unreachable object counts as undecodable
            undecodable += 1
            continue
        try:
            report, frames_by_position = run_quality_check(
                video_bytes, session_id=entry.session_id, settings=settings.qc
            )
        except RuntimeError:
            undecodable += 1
            continue

        if report.overall == "PASS":
            passed += 1
        else:
            failed += 1

        for position_result in report.positions:
            if position_result.passed:
                position_pass_counts[position_result.position] += 1

        for frames in frames_by_position.values():
            for frame_quality in frames:
                blur_values.append(frame_quality.blur)
                brightness_values.append(frame_quality.brightness)

    total_scored = passed + failed
    coverage = [
        PositionCoverage(
            position=position,
            videos_with_pass=position_pass_counts.get(position, 0),
            total_videos_scored=total_scored,
        )
        for position in CLOCK_POSITIONS
    ]

    report = EDAReport(
        snapshot_id=snapshot_id,
        total_videos=len(videos),
        videos_qc_passed=passed,
        videos_qc_failed=failed,
        videos_undecodable=undecodable,
        qc_pass_ratio=(passed / total_scored) if total_scored else 0.0,
        unique_users=len(manifest.user_ids),
        unique_sessions=len(manifest.session_ids),
        videos_per_user=dict(videos_per_user),
        coverage_by_position=coverage,
        blur_score_stats=_score_stats(blur_values),
        brightness_score_stats=_score_stats(brightness_values),
    )

    markdown = render_markdown(report)
    _upload_reports(client, settings, snapshot_id, report, markdown)
    return report


def render_markdown(report: EDAReport) -> str:
    """Human-readable summary - numbers only, no plotting/images per task
    instructions."""
    lines = [
        f"# EDA report - snapshot `{report.snapshot_id}`",
        "",
        f"Generated at: {report.generated_at.isoformat()}",
        "",
        "## Summary",
        "",
        f"- Total videos: {report.total_videos}",
        f"- Unique users: {report.unique_users}",
        f"- Unique sessions: {report.unique_sessions}",
        f"- QC passed: {report.videos_qc_passed}",
        f"- QC failed: {report.videos_qc_failed}",
        f"- Undecodable: {report.videos_undecodable}",
        f"- QC pass ratio: {report.qc_pass_ratio:.2%}",
        "",
        "## Videos per user",
        "",
        "| user_id | videos |",
        "|---|---|",
    ]
    for user_id, count in sorted(report.videos_per_user.items()):
        lines.append(f"| {user_id} | {count} |")

    lines += [
        "",
        "## Coverage by clock position",
        "",
        "| Position | Videos passing | Total scored |",
        "|---|---|---|",
    ]
    for coverage in report.coverage_by_position:
        lines.append(
            f"| {coverage.position} | {coverage.videos_with_pass} | "
            f"{coverage.total_videos_scored} |"
        )

    def _stat_lines(title: str, stats: ScoreStats) -> list[str]:
        return [
            "",
            f"## {title}",
            "",
            f"- count: {stats.count}",
            f"- mean: {stats.mean:.2f}",
            f"- min: {stats.min:.2f}",
            f"- max: {stats.max:.2f}",
            f"- stdev: {stats.stdev:.2f}",
        ]

    lines += _stat_lines("Blur score (variance of Laplacian)", report.blur_score_stats)
    lines += _stat_lines("Brightness score", report.brightness_score_stats)
    lines.append("")
    return "\n".join(lines)


def _upload_reports(
    client: Any, settings: Settings, snapshot_id: str, report: EDAReport, markdown: str
) -> None:
    prefix = f"datasets/{snapshot_id}"
    client.put_object(
        Bucket=settings.s3.bucket,
        Key=f"{prefix}/eda_report.json",
        Body=report.model_dump_json(indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    client.put_object(
        Bucket=settings.s3.bucket,
        Key=f"{prefix}/eda_report.md",
        Body=markdown.encode("utf-8"),
        ContentType="text/markdown",
    )
