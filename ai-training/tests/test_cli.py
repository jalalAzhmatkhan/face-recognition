"""CLI wiring for TR-04 (`snapshot`) / TR-05 (`eda`) subcommands - the real
`build_snapshot`/`build_eda_report` are monkeypatched out so this never
touches real Postgres/S3."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import ai_training.cli as cli
from ai_training.data.snapshots import DatasetSnapshot


def test_parse_filters_splits_key_value_pairs() -> None:
    assert cli._parse_filters(["external_ref=EMP001", "created_after=2026-01-01"]) == {
        "external_ref": "EMP001",
        "created_after": "2026-01-01",
    }


def test_parse_filters_rejects_missing_equals_sign() -> None:
    with pytest.raises(ValueError, match="key=value"):
        cli._parse_filters(["not-a-kv-pair"])


def test_main_snapshot_prints_snapshot_id_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_snapshot = DatasetSnapshot(snapshot_id="snap-xyz")
    monkeypatch.setattr(cli, "build_snapshot", lambda settings, filters: fake_snapshot)

    exit_code = cli.main(["snapshot", "--filter", "external_ref=EMP001"])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "snap-xyz"


def test_main_snapshot_bad_filter_syntax_returns_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(["snapshot", "--filter", "not-a-kv-pair"])

    assert exit_code == 2
    assert "snapshot:" in capsys.readouterr().err


def test_main_snapshot_propagates_unsupported_filter_key_as_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _raise(settings: object, filters: dict[str, str]) -> DatasetSnapshot:
        raise ValueError("unsupported filter key(s): ['bogus']")

    monkeypatch.setattr(cli, "build_snapshot", _raise)

    exit_code = cli.main(["snapshot", "--filter", "bogus=1"])

    assert exit_code == 2
    assert "unsupported filter" in capsys.readouterr().err


def test_main_evaluate_invokes_evaluate_candidate_and_prints_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from ai_training.evaluation.metrics import EvalReport

    calls: dict[str, str] = {}
    fake_report = EvalReport(
        recall=0.99,
        f1=0.95,
        precision=0.92,
        latency_ms_p95=12.3,
        far=0.005,
        model_version="adaface-ir101-webface12m",
        benchmark_id="snap-xyz",
    )

    def _fake_evaluate_candidate(settings: object, model_version: str, benchmark_id: str) -> object:
        calls["model_version"] = model_version
        calls["benchmark_id"] = benchmark_id
        return fake_report

    monkeypatch.setattr(
        "ai_training.evaluation.metrics.evaluate_candidate", _fake_evaluate_candidate
    )

    exit_code = cli.main(
        ["evaluate", "--model-version", "adaface-ir101-webface12m", "--benchmark-id", "snap-xyz"]
    )

    assert exit_code == 0
    assert calls == {"model_version": "adaface-ir101-webface12m", "benchmark_id": "snap-xyz"}
    out = capsys.readouterr().out
    assert "snap-xyz" in out
    assert "0.99" in out


def test_main_eda_invokes_build_eda_report_with_snapshot_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: dict[str, str] = {}

    def _fake_build_eda_report(settings: object, snapshot_id: str) -> MagicMock:
        calls["snapshot_id"] = snapshot_id
        return MagicMock()

    monkeypatch.setattr("ai_training.eda.report.build_eda_report", _fake_build_eda_report)

    exit_code = cli.main(["eda", "--snapshot-id", "snap-xyz"])

    assert exit_code == 0
    assert calls["snapshot_id"] == "snap-xyz"
    assert "snap-xyz" in capsys.readouterr().out
