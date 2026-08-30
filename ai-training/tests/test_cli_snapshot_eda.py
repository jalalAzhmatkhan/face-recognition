"""CLI `snapshot`/`eda` subcommands (TR-04/TR-05), monkeypatched so no real
DB/S3 is touched."""

from __future__ import annotations

import pytest

import ai_training.cli as cli_module
from ai_training.data.snapshots import DatasetSnapshot


def test_snapshot_command_parses_filters_and_prints_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, object] = {}

    def fake_build_snapshot(settings: object, filters: dict[str, str]) -> DatasetSnapshot:
        captured["filters"] = filters
        return DatasetSnapshot(snapshot_id="snap-123", media_keys=[])

    monkeypatch.setattr(cli_module, "build_snapshot", fake_build_snapshot)

    exit_code = cli_module.main(
        ["snapshot", "--filter", "external_ref=emp-1", "--filter", "kind=video"]
    )

    assert exit_code == 0
    assert captured["filters"] == {"external_ref": "emp-1", "kind": "video"}
    out = capsys.readouterr().out
    assert out.strip() == "snap-123"


def test_snapshot_command_rejects_malformed_filter(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli_module.main(["snapshot", "--filter", "not-a-kv-pair"])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "key=value" in err


def test_eda_command_invokes_build_eda_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: dict[str, object] = {}

    def fake_build_eda_report(settings: object, snapshot_id: str) -> object:
        calls["snapshot_id"] = snapshot_id
        return object()

    monkeypatch.setattr("ai_training.eda.report.build_eda_report", fake_build_eda_report)

    exit_code = cli_module.main(["eda", "--snapshot-id", "snap-123"])

    assert exit_code == 0
    assert calls["snapshot_id"] == "snap-123"
    out = capsys.readouterr().out
    assert "snap-123" in out
