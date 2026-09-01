"""EC-TR-05 PAD collection scan/upload tooling (TSD-EC B-4/ASM-EC-12).

Uses real temp-directory files (structure/parsing is the thing under test)
but a mocked S3 client - no real Postgres/S3, per project convention.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_training.config import Settings
from ai_training.data.pad_collection import (
    PadCollectionReport,
    load_pad_manifest,
    scan_pad_collection,
    upload_pad_collection,
)


def _settings() -> Settings:
    return Settings(_env_file=None)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake-clip-bytes")


def test_scan_parses_bona_fide_and_attack_paths(tmp_path: Path) -> None:
    _touch(tmp_path / "bona_fide" / "subj-1" / "normal" / "on" / "clip.mp4")
    _touch(tmp_path / "attack" / "subj-1" / "print_01" / "am2" / "dark" / "clip.mp4")

    clips, _report = scan_pad_collection(tmp_path)

    by_role = {clip.role: clip for clip in clips}
    bona_fide = by_role["bona_fide"]
    assert bona_fide.subject_id == "subj-1"
    assert bona_fide.condition == "normal"
    assert bona_fide.mask == "on"
    assert bona_fide.instrument_id is None

    attack = by_role["attack"]
    assert attack.subject_id == "subj-1"
    assert attack.instrument_id == "print_01"
    assert attack.mask == "am2"
    assert attack.condition == "dark"


@pytest.mark.parametrize(
    "relative",
    [
        "bona_fide/subj-1/normal/clip.mp4",  # missing mask segment
        "bona_fide/subj-1/sideways/on/clip.mp4",  # bad condition
        "bona_fide/subj-1/normal/sideways/clip.mp4",  # bad mask
        "attack/subj-1/unknown_01/am2/dark/clip.mp4",  # instrument missing print_/replay_ prefix
        "attack/subj-1/print_01/bogus_mask/dark/clip.mp4",  # bad attack mask
        "attack/subj-1/print_01/am2/sideways/clip.mp4",  # bad attack condition
        "unknown_role/subj-1/clip.mp4",  # bad top-level role
    ],
)
def test_scan_rejects_malformed_paths(tmp_path: Path, relative: str) -> None:
    _touch(tmp_path / relative)
    with pytest.raises(ValueError):
        scan_pad_collection(tmp_path)


def test_report_flags_missing_bona_fide_combos(tmp_path: Path) -> None:
    # subj-1 only has "normal/on" -- missing the other 3 required combos.
    _touch(tmp_path / "bona_fide" / "subj-1" / "normal" / "on" / "clip.mp4")

    _clips, report = scan_pad_collection(tmp_path)

    assert report.subjects_missing_combos == {
        "subj-1": ["dark/off", "dark/on", "normal/off"]
    }
    assert report.bona_fide_meets_minimum is False
    assert report.is_ready_for_finetune is False


def test_report_counts_distinct_print_and_replay_instruments(tmp_path: Path) -> None:
    for i in range(3):
        _touch(tmp_path / "attack" / "subj-1" / f"print_{i}" / "unmasked" / "normal" / "clip.mp4")
    for i in range(2):
        _touch(tmp_path / "attack" / "subj-1" / f"replay_{i}" / "unmasked" / "normal" / "clip.mp4")

    _clips, report = scan_pad_collection(tmp_path)

    assert report.print_instrument_count == 3
    assert report.replay_instrument_count == 2
    assert report.attack_instruments_meet_minimum is False  # replay short of 3
    assert report.has_am2_attack is False


def _build_full_valid_collection(tmp_path: Path) -> None:
    """30 bona-fide subjects with all 4 combos, 3 print + 3 replay
    instruments, and at least one AM2 attack -- exactly meets the
    ASM-EC-12/OQ-2 floor."""
    for s in range(30):
        subject = f"subj-{s}"
        for condition in ("normal", "dark"):
            for mask in ("on", "off"):
                _touch(tmp_path / "bona_fide" / subject / condition / mask / "clip.mp4")
    for i in range(3):
        _touch(tmp_path / "attack" / "subj-0" / f"print_{i}" / "unmasked" / "normal" / "clip.mp4")
    for i in range(3):
        _touch(tmp_path / "attack" / "subj-0" / f"replay_{i}" / "unmasked" / "normal" / "clip.mp4")
    _touch(tmp_path / "attack" / "subj-0" / "print_0" / "am2" / "dark" / "am2_clip.mp4")


def test_report_is_ready_for_finetune_once_minimum_spec_is_met(tmp_path: Path) -> None:
    _build_full_valid_collection(tmp_path)

    _clips, report = scan_pad_collection(tmp_path)

    assert report == PadCollectionReport(
        bona_fide_subject_count=30,
        bona_fide_meets_minimum=True,
        subjects_missing_combos={},
        print_instrument_count=3,
        replay_instrument_count=3,
        attack_instruments_meet_minimum=True,
        has_am2_attack=True,
        is_ready_for_finetune=True,
    )


def test_upload_pad_collection_uploads_each_clip_under_collection_prefix(
    tmp_path: Path,
) -> None:
    _touch(tmp_path / "bona_fide" / "subj-1" / "normal" / "on" / "clip.mp4")
    s3 = MagicMock()
    settings = _settings()

    manifest = upload_pad_collection(settings, tmp_path, "collection-abc", s3_client=s3)

    assert manifest.total_clip_count == 1
    assert manifest.clips[0].s3_key == "pad/collection-abc/bona_fide/subj-1/normal/on/clip.mp4"
    # One PUT for the clip, one for the manifest.
    assert s3.put_object.call_count == 2
    clip_call = s3.put_object.call_args_list[0].kwargs
    assert clip_call["Bucket"] == settings.s3.bucket
    assert clip_call["Key"] == "pad/collection-abc/bona_fide/subj-1/normal/on/clip.mp4"


def test_upload_pad_collection_uploads_manifest_to_expected_key(tmp_path: Path) -> None:
    _touch(tmp_path / "bona_fide" / "subj-1" / "normal" / "on" / "clip.mp4")
    s3 = MagicMock()
    settings = _settings()

    manifest = upload_pad_collection(settings, tmp_path, "collection-abc", s3_client=s3)

    manifest_call = s3.put_object.call_args_list[-1].kwargs
    assert manifest_call["Key"] == "pad/collection-abc/manifest.json"
    body = json.loads(manifest_call["Body"])
    assert body["collection_id"] == "collection-abc"
    assert body["total_clip_count"] == manifest.total_clip_count


def test_upload_pad_collection_raises_before_any_upload_on_malformed_structure(
    tmp_path: Path,
) -> None:
    _touch(tmp_path / "bona_fide" / "subj-1" / "sideways" / "on" / "clip.mp4")
    s3 = MagicMock()

    with pytest.raises(ValueError):
        upload_pad_collection(_settings(), tmp_path, "collection-abc", s3_client=s3)

    s3.put_object.assert_not_called()


class _BytesReader:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


def test_load_pad_manifest_round_trips_what_upload_wrote(tmp_path: Path) -> None:
    _touch(tmp_path / "bona_fide" / "subj-1" / "normal" / "on" / "clip.mp4")
    uploaded: dict[str, bytes] = {}

    def _fake_put(*, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        uploaded[Key] = Body

    s3_write = MagicMock()
    s3_write.put_object.side_effect = lambda **kwargs: _fake_put(**kwargs)
    settings = _settings()

    built = upload_pad_collection(settings, tmp_path, "collection-xyz", s3_client=s3_write)

    s3_read = MagicMock()
    s3_read.get_object.return_value = {
        "Body": _BytesReader(uploaded["pad/collection-xyz/manifest.json"])
    }

    loaded = load_pad_manifest(settings, "collection-xyz", s3_client=s3_read)

    assert loaded == built
