"""Presentation-attack-detection (PAD) dataset collection tooling (EC-TR-05,
TSD-edge-cases.md B-4/ASM-EC-12/OQ-2).

PAD media is collected by an operator against real deployment cameras
(bona fide staff + print/replay attacks) - it does NOT belong to any one
enrolled user, so it is deliberately kept OUT of the `media_objects` /
enrollment presign flow entirely (see `ai_training.data.snapshots` module
docstring for that pool). Instead it goes straight to a dedicated S3
prefix, `pad/{collection_id}/...`, uploaded by this module's
`upload_pad_collection()` - manifest-only in spirit (the manifest never
embeds media bytes), same as `ai_training.data.snapshots.build_snapshot`,
but there is no DB row to query: the manifest is built by walking a local
directory tree the operator already populated.

Expected local directory layout (validated by `scan_pad_collection`)::

    {local_dir}/
      bona_fide/{subject_id}/{condition}/{mask}/<clip file>
      attack/{subject_id}/{instrument_id}/{mask}/{condition}/<clip file>

    condition   in {"normal", "dark"}
    mask        bona_fide: {"on", "off"}          (wearing a real mask or not)
                attack:    {"unmasked", "am1", "am2"}
                             AM1/AM2 = Fang's mask-attack taxonomy: AM1 is a
                             mask *printed/rendered onto* the print/replay
                             medium, AM2 is a REAL mask physically placed on
                             top of the print/replay medium (the blind spot
                             ASM-EC-12 calls out as mandatory to include).
    instrument_id   attack only, must start with "print_" or "replay_" -
                    identifies one physical print/replay instrument, so the
                    completeness report can count distinct instruments per
                    attack type (spec: >=3 of each, OQ-2).

A malformed path (wrong segment count, unrecognized condition/mask/role, an
instrument_id without a print_/replay_ prefix) is a hard `ValueError` - the
operator's upload has a real structural mistake, not just an incomplete
collection. Missing coverage (not enough subjects yet, a subject missing
one of the 4 bona-fide clips, fewer than 3 print/replay instruments, no
AM2 attack yet) is NOT an error: real-world collection happens
incrementally over time (EC-OPS-02 is a separate, long-lead task), so this
only reports it via `PadCollectionReport` - the "checklist kelengkapan"
EC-TR-05's acceptance criteria asks for - never blocks the upload.
"""

from __future__ import annotations

import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ai_training.config import Settings
from ai_training.storage import build_s3_client

BONA_FIDE_CONDITIONS = frozenset({"normal", "dark"})
BONA_FIDE_MASKS = frozenset({"on", "off"})
ATTACK_CONDITIONS = frozenset({"normal", "dark"})
ATTACK_MASKS = frozenset({"unmasked", "am1", "am2"})
ATTACK_INSTRUMENT_PREFIXES = ("print_", "replay_")

# ASM-EC-12/OQ-2 minimums (ideal range is 50-80 subjects / more instruments,
# but these are the floor `PadCollectionReport.is_ready_for_finetune` gates
# on - B-3's FINETUNE_LIVENESS job is the actual consumer of "ready").
MIN_BONA_FIDE_SUBJECTS = 30
MIN_INSTRUMENTS_PER_ATTACK_TYPE = 3

# Every combo a bona-fide subject must eventually have a clip for.
_REQUIRED_BONA_FIDE_COMBOS = frozenset(
    (condition, mask) for condition in BONA_FIDE_CONDITIONS for mask in BONA_FIDE_MASKS
)


class PadClip(BaseModel):
    """One PAD media file, parsed from its path under `local_dir` (before
    upload) or under the `pad/{collection_id}/` S3 prefix (after)."""

    relative_path: str
    role: str  # "bona_fide" | "attack"
    subject_id: str
    condition: str
    mask: str
    instrument_id: str | None = None  # attack only
    s3_key: str = ""  # filled in by upload_pad_collection


class PadCollectionReport(BaseModel):
    """Completeness checklist against the ASM-EC-12/OQ-2 minimum spec -
    report-only, see module docstring on why nothing here blocks upload."""

    bona_fide_subject_count: int = 0
    bona_fide_meets_minimum: bool = False
    # subject_id -> sorted "condition/mask" combos that subject is missing.
    subjects_missing_combos: dict[str, list[str]] = Field(default_factory=dict)
    print_instrument_count: int = 0
    replay_instrument_count: int = 0
    attack_instruments_meet_minimum: bool = False
    has_am2_attack: bool = False
    is_ready_for_finetune: bool = False


class PadCollectionManifest(BaseModel):
    collection_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    bucket: str = ""
    prefix: str = ""
    clips: list[PadClip] = Field(default_factory=list)
    report: PadCollectionReport = Field(default_factory=PadCollectionReport)
    total_clip_count: int = 0


def _pad_prefix(collection_id: str) -> str:
    return f"pad/{collection_id}"


def _manifest_key(collection_id: str) -> str:
    return f"{_pad_prefix(collection_id)}/manifest.json"


def _parse_clip(local_dir: Path, file_path: Path) -> PadClip:
    relative = file_path.relative_to(local_dir)
    parts = relative.parts
    role = parts[0] if parts else ""

    if role == "bona_fide":
        if len(parts) != 5:
            raise ValueError(
                f"malformed bona_fide PAD path (expected "
                f"bona_fide/<subject_id>/<condition>/<mask>/<file>): {relative}"
            )
        _role, subject_id, condition, mask, _file = parts
        if condition not in BONA_FIDE_CONDITIONS:
            raise ValueError(f"unsupported bona_fide condition {condition!r} in path: {relative}")
        if mask not in BONA_FIDE_MASKS:
            raise ValueError(f"unsupported bona_fide mask {mask!r} in path: {relative}")
        return PadClip(
            relative_path=relative.as_posix(),
            role="bona_fide",
            subject_id=subject_id,
            condition=condition,
            mask=mask,
        )

    if role == "attack":
        if len(parts) != 6:
            raise ValueError(
                f"malformed attack PAD path (expected "
                f"attack/<subject_id>/<instrument_id>/<mask>/<condition>/<file>): {relative}"
            )
        _role, subject_id, instrument_id, mask, condition, _file = parts
        if not instrument_id.startswith(ATTACK_INSTRUMENT_PREFIXES):
            raise ValueError(
                f"attack instrument_id must start with 'print_' or 'replay_', "
                f"got {instrument_id!r} in path: {relative}"
            )
        if mask not in ATTACK_MASKS:
            raise ValueError(f"unsupported attack mask {mask!r} in path: {relative}")
        if condition not in ATTACK_CONDITIONS:
            raise ValueError(f"unsupported attack condition {condition!r} in path: {relative}")
        return PadClip(
            relative_path=relative.as_posix(),
            role="attack",
            subject_id=subject_id,
            condition=condition,
            mask=mask,
            instrument_id=instrument_id,
        )

    raise ValueError(f"PAD path must start with 'bona_fide/' or 'attack/', got: {relative}")


def _build_report(clips: list[PadClip]) -> PadCollectionReport:
    bona_fide = [clip for clip in clips if clip.role == "bona_fide"]
    attacks = [clip for clip in clips if clip.role == "attack"]

    combos_by_subject: dict[str, set[tuple[str, str]]] = {}
    for clip in bona_fide:
        combos_by_subject.setdefault(clip.subject_id, set()).add((clip.condition, clip.mask))

    subjects_missing_combos = {
        subject_id: sorted(f"{condition}/{mask}" for condition, mask in missing)
        for subject_id, combos in combos_by_subject.items()
        if (missing := _REQUIRED_BONA_FIDE_COMBOS - combos)
    }

    print_instruments = {
        c.instrument_id
        for c in attacks
        if c.instrument_id and c.instrument_id.startswith("print_")
    }
    replay_instruments = {
        c.instrument_id
        for c in attacks
        if c.instrument_id and c.instrument_id.startswith("replay_")
    }
    attack_instruments_meet_minimum = (
        len(print_instruments) >= MIN_INSTRUMENTS_PER_ATTACK_TYPE
        and len(replay_instruments) >= MIN_INSTRUMENTS_PER_ATTACK_TYPE
    )
    has_am2 = any(c.mask == "am2" for c in attacks)
    bona_fide_subject_count = len(combos_by_subject)
    bona_fide_meets_minimum = bona_fide_subject_count >= MIN_BONA_FIDE_SUBJECTS

    return PadCollectionReport(
        bona_fide_subject_count=bona_fide_subject_count,
        bona_fide_meets_minimum=bona_fide_meets_minimum,
        subjects_missing_combos=subjects_missing_combos,
        print_instrument_count=len(print_instruments),
        replay_instrument_count=len(replay_instruments),
        attack_instruments_meet_minimum=attack_instruments_meet_minimum,
        has_am2_attack=has_am2,
        is_ready_for_finetune=(
            bona_fide_meets_minimum
            and not subjects_missing_combos
            and attack_instruments_meet_minimum
            and has_am2
        ),
    )


def scan_pad_collection(local_dir: Path | str) -> tuple[list[PadClip], PadCollectionReport]:
    """Walk `local_dir`, parse every file into a `PadClip`, and build the
    completeness report. Raises `ValueError` on the first structurally
    malformed path (see module docstring) - never on incomplete-but-valid
    coverage.
    """
    local_dir = Path(local_dir)
    files = sorted(p for p in local_dir.rglob("*") if p.is_file())
    clips = [_parse_clip(local_dir, f) for f in files]
    return clips, _build_report(clips)


def upload_pad_collection(
    settings: Settings,
    local_dir: Path | str,
    collection_id: str,
    *,
    s3_client: Any = None,
) -> PadCollectionManifest:
    """Validate + upload a local PAD collection to
    `s3://{bucket}/pad/{collection_id}/...`, then upload a manifest
    alongside it (`pad/{collection_id}/manifest.json`) - the media itself is
    real bytes (unlike `build_snapshot`'s DB-referencing manifest, there is
    no pre-existing S3 object to just reference), but the manifest again
    never embeds those bytes, only per-clip metadata + keys.
    """
    local_dir = Path(local_dir)
    clips, report = scan_pad_collection(local_dir)

    client = s3_client if s3_client is not None else build_s3_client(settings)
    prefix = _pad_prefix(collection_id)
    uploaded_clips: list[PadClip] = []
    for clip in clips:
        s3_key = f"{prefix}/{clip.relative_path}"
        content_type = mimetypes.guess_type(clip.relative_path)[0] or "application/octet-stream"
        with (local_dir / clip.relative_path).open("rb") as fh:
            client.put_object(
                Bucket=settings.s3.bucket,
                Key=s3_key,
                Body=fh.read(),
                ContentType=content_type,
            )
        uploaded_clips.append(clip.model_copy(update={"s3_key": s3_key}))

    manifest = PadCollectionManifest(
        collection_id=collection_id,
        bucket=settings.s3.bucket,
        prefix=prefix,
        clips=uploaded_clips,
        report=report,
        total_clip_count=len(uploaded_clips),
    )
    client.put_object(
        Bucket=settings.s3.bucket,
        Key=_manifest_key(collection_id),
        Body=manifest.model_dump_json(indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    return manifest


def load_pad_manifest(
    settings: Settings, collection_id: str, *, s3_client: Any = None
) -> PadCollectionManifest:
    """Read back the manifest previously written by `upload_pad_collection()`."""
    client = s3_client if s3_client is not None else build_s3_client(settings)
    response = client.get_object(Bucket=settings.s3.bucket, Key=_manifest_key(collection_id))
    body = response["Body"].read()
    return PadCollectionManifest.model_validate_json(body)
