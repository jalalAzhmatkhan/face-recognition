"""Slice catalog + versioned manifest + rule-of-30 (EC-TR-01 / TSD-EC D-7,
OQ-8) against a mocked S3 client - no real S3/Postgres, per project
testing convention (mirrors test_snapshots.py)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from ai_training.config import Settings
from ai_training.evaluation.slices import (
    MIN_GENUINE_DECISIONS,
    MIN_GENUINE_IDENTITIES,
    MIN_IMPOSTOR_COMPARISONS,
    SLICE_CATALOG,
    SliceManifest,
    check_rule_of_30,
    load_slice_manifest,
    save_slice_manifest,
    skeleton_manifest,
    slice_manifest_key,
)


def _settings() -> Settings:
    return Settings(_env_file=None)


def test_catalog_lists_every_d7_slice() -> None:
    expected = {
        "masked-riil",
        "masked-sintetis",
        "dark",
        "kacamata",
        "hijab",
        "blur",
        "low-res",
        "per-demografi-utama",
        "masked-x-demografi",
        "kontak-kosmetik",
    }
    assert set(SLICE_CATALOG) == expected


def test_catalog_critical_gate_slices_match_tsd_d7_3_minimum() -> None:
    critical = {name for name, spec in SLICE_CATALOG.items() if spec.is_gate}
    assert critical == {"masked-riil", "dark", "low-res", "hijab", "per-demografi-utama"}


def test_catalog_cosmetic_lens_is_smoke_test_not_gate() -> None:
    spec = SLICE_CATALOG["kontak-kosmetik"]
    assert spec.is_smoke_test is True
    assert spec.is_gate is False


def test_catalog_masked_x_demografi_is_report_only_not_gate() -> None:
    spec = SLICE_CATALOG["masked-x-demografi"]
    assert spec.report_only is True
    assert spec.is_gate is False


def test_check_rule_of_30_passes_at_full_scale() -> None:
    report = check_rule_of_30(
        "dark",
        genuine_identity_count=30,
        genuine_probe_count=600,
        impostor_comparison_count=10_000,
    )
    assert report.passes is True
    assert report.genuine_identity_count_ok is True
    assert report.genuine_probe_count_ok is True
    assert report.impostor_comparison_count_ok is True


def test_check_rule_of_30_fails_below_thresholds() -> None:
    report = check_rule_of_30(
        "dark",
        genuine_identity_count=5,
        genuine_probe_count=10,
        impostor_comparison_count=100,
    )
    assert report.passes is False
    assert report.genuine_identity_count_ok is False
    assert report.genuine_probe_count_ok is False
    assert report.impostor_comparison_count_ok is False


def test_check_rule_of_30_smoke_test_slice_always_passes() -> None:
    report = check_rule_of_30(
        "kontak-kosmetik",
        genuine_identity_count=5,
        genuine_probe_count=8,
        impostor_comparison_count=0,
    )
    assert report.passes is True
    assert report.is_smoke_test_exempt is True


def test_rule_of_30_constants_match_oq8() -> None:
    assert MIN_GENUINE_IDENTITIES == 30
    assert MIN_GENUINE_DECISIONS == 600
    assert MIN_IMPOSTOR_COMPARISONS == 10_000


def test_skeleton_manifest_has_no_data_and_correct_gate_flag() -> None:
    manifest = skeleton_manifest("hijab")
    assert manifest.data_status == "awaiting_real_data"
    assert manifest.media == []
    assert manifest.is_gate is True
    assert manifest.rule_of_30().passes is False


def test_skeleton_manifest_smoke_test_slice_passes_rule_of_30_even_empty() -> None:
    manifest = skeleton_manifest("kontak-kosmetik")
    assert manifest.rule_of_30().passes is True


def test_slice_manifest_key_matches_documented_s3_convention() -> None:
    assert slice_manifest_key("dark", "v1") == "benchmarks/edge-cases/dark/v1/manifest.json"


def test_save_slice_manifest_uploads_to_expected_s3_key() -> None:
    manifest = SliceManifest(
        slice_name="dark",
        version="v1",
        genuine_identity_count=30,
        genuine_probe_count=600,
        impostor_comparison_count=10_000,
    )
    s3 = MagicMock()
    settings = _settings()

    save_slice_manifest(settings, manifest, s3_client=s3)

    s3.put_object.assert_called_once()
    _args, kwargs = s3.put_object.call_args
    assert kwargs["Bucket"] == settings.s3.bucket
    assert kwargs["Key"] == "benchmarks/edge-cases/dark/v1/manifest.json"
    body = json.loads(kwargs["Body"])
    assert body["slice_name"] == "dark"
    assert body["version"] == "v1"


class _BytesReader:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


def test_load_slice_manifest_round_trips_saved_manifest() -> None:
    manifest = SliceManifest(slice_name="low-res", version="v2", genuine_identity_count=3)
    settings = _settings()

    uploaded: dict[str, bytes] = {}
    s3_write = MagicMock()
    s3_write.put_object.side_effect = lambda **kwargs: uploaded.__setitem__(
        kwargs["Key"], kwargs["Body"]
    )
    save_slice_manifest(settings, manifest, s3_client=s3_write)

    s3_read = MagicMock()
    key = slice_manifest_key("low-res", "v2")
    s3_read.get_object.return_value = {"Body": _BytesReader(uploaded[key])}

    loaded = load_slice_manifest(settings, "low-res", "v2", s3_client=s3_read)

    assert loaded == manifest
    s3_read.get_object.assert_called_once_with(Bucket=settings.s3.bucket, Key=key)
