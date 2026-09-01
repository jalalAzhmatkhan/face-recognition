"""CLI wiring for EC-TR-01's `slice-catalog` / `build-synthetic-slice`
subcommands - `save_slice_manifest` is monkeypatched so this never touches
real S3 (mirrors test_cli.py's `build_snapshot` monkeypatch convention)."""

from __future__ import annotations

import pytest

import ai_training.cli as cli
import ai_training.evaluation.slices as slices_module


def test_slice_catalog_lists_all_slices(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(["slice-catalog"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "dark" in out
    assert "GATE" in out
    assert "kontak-kosmetik" in out
    assert "SMOKE" in out


def test_slice_catalog_detail_for_unknown_slice_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(["slice-catalog", "--slice", "not-a-real-slice"])
    assert exit_code == 2
    assert "unknown slice" in capsys.readouterr().err


def test_slice_catalog_detail_prints_spec_and_skeleton(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(["slice-catalog", "--slice", "hijab"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert '"name": "hijab"' in out
    assert '"data_status": "awaiting_real_data"' in out


def test_build_synthetic_slice_uploads_and_prints_manifest(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    uploaded = {}
    monkeypatch.setattr(
        slices_module,
        "save_slice_manifest",
        lambda settings, manifest, s3_client=None: uploaded.setdefault("manifest", manifest),
    )

    exit_code = cli.main(
        [
            "build-synthetic-slice",
            "--slice",
            "dark",
            "--version",
            "v1-smoke",
            "--n-identities",
            "3",
            "--probes-per-identity",
            "2",
        ]
    )

    assert exit_code == 0
    assert uploaded["manifest"].slice_name == "dark"
    assert uploaded["manifest"].data_status == "synthetic_placeholder"
    assert uploaded["manifest"].genuine_identity_count == 3
    assert uploaded["manifest"].genuine_probe_count == 6
    out = capsys.readouterr().out
    assert '"slice_name": "dark"' in out


def test_build_synthetic_slice_rejects_non_synthesizable_slice_via_argparse() -> None:
    with pytest.raises(SystemExit):
        cli.main(["build-synthetic-slice", "--slice", "hijab", "--version", "v1"])
