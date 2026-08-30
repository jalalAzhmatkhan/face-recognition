"""Smoke tests for the training pipeline scaffold (TR-01)."""

import pytest

from ai_training.cli import build_parser, main
from ai_training.config import Settings
from ai_training.evaluation.metrics import EvalReport
from ai_training.preprocessing.frames import POSE_BIN_YAWS, assign_pose_bin


def test_packages_importable() -> None:
    """All pipeline packages import without torch/mlflow/boto3 installed."""
    import ai_training.data.snapshots
    import ai_training.embedding.extractor
    import ai_training.evaluation.metrics
    import ai_training.preprocessing.frames
    import ai_training.training.finetune  # noqa: F401


def test_settings_defaults_have_no_credentials() -> None:
    settings = Settings(_env_file=None)
    assert settings.db.dsn == ""
    assert settings.mlflow.tracking_uri == ""
    assert settings.s3.bucket == "frac-media"
    assert settings.training.target_recall == pytest.approx(0.98)


def test_cli_help_and_config(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0  # prints help
    assert main(["config"]) == 0
    out = capsys.readouterr().out
    assert "frac-media" in out


def test_cli_stub_commands_exit_nonzero() -> None:
    assert main(["finetune", "--snapshot-id", "snap-1"]) == 2


def test_cli_parser_has_all_stage_commands() -> None:
    parser = build_parser()
    text = parser.format_help()
    for cmd in ("config", "snapshot", "finetune", "evaluate"):
        assert cmd in text


def test_pose_bins() -> None:
    assert 0 in POSE_BIN_YAWS
    assert assign_pose_bin(17.0) == 15
    assert assign_pose_bin(-88.0) == -90


def test_eval_report_schema() -> None:
    report = EvalReport(
        recall=0.99, f1=0.98, precision=0.97, latency_ms_p95=42.0, far=0.0005,
        model_version="v1",
    )
    assert report.recall >= report.f1 >= report.precision
