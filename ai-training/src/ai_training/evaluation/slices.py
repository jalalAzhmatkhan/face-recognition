"""Edge-case benchmark slice catalog + versioned manifest (EC-TR-01 /
TSD-EC D-7, OQ-8).

A "slice" is a labeled sub-population of the frozen benchmark (e.g.
`dark`, `masked-riil`, `hijab`) with its own Recall/F1/Precision/CI report
and, for the critical slices, its own no-regression gate (EC-QA-01). This
module owns:

1. `SLICE_CATALOG` - the fixed list of slices TSD-EC D-7.1 calls for, each
   tagged with whether it currently GATES promotion, is a smoke test
   (reported, never gates - lensa kosmetik, OQ-8/ASM-EC-11), or is
   report-only pending a policy decision (masked x demografi interaction,
   R-4/REV).
2. `SliceManifest` - the versioned/frozen manifest format, uploaded to S3 at
   `benchmarks/edge-cases/{slice_name}/{version}/manifest.json` (mirrors
   `ai_training.data.snapshots`'s `datasets/{snapshot_id}/manifest.json`
   convention: a manifest is a reference to media, never the media bytes
   themselves - repo rule #1, media never lives outside S3/in-memory).
3. `check_rule_of_30` - composition validator against OQ-8's acceptance
   numbers (genuine >=30 identities x >=20 probes >= 600, ideal 1000;
   impostor >= 10000), independent of whether the slice's media come from
   real capture (EC-OPS-02, not yet collected) or the small synthetic
   placeholder this task ships (`ai_training.evaluation.synthetic_slices`).

**Honesty note (do not remove)**: as of this task (EC-TR-01, Gelombang 0),
every slice in `SLICE_CATALOG` has `data_status="awaiting_real_data"` except
where a synthetic placeholder was actually built and is explicitly labeled
`data_status="synthetic_placeholder"`. No slice in this codebase currently
satisfies `check_rule_of_30(...).passes` at real-data scale - that is
expected and tracked as EC-OPS-02, not a bug here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from ai_training.config import Settings
from ai_training.data.snapshots import MediaEntry


class SliceSpec(BaseModel):
    """Static catalog entry describing ONE benchmark slice (TSD-EC D-7.1)."""

    name: str
    description: str
    # Slice participates in EC-QA-01's no-regression-bertoleransi-CI gate.
    # Per TSD-EC D-7.3, the minimum critical set is: masked-riil, dark,
    # low-res, hijab, per-demografi-utama.
    is_gate: bool
    # Lensa kosmetik: 5-10 samples, explicitly NOT statistically significant
    # (OQ-8/ASM-EC-11) - reported, never gates, and never expected to reach
    # rule-of-30 scale.
    is_smoke_test: bool = False
    # Reported for visibility but not yet wired to the gate (R-4/REV: masked
    # x demografi interaction - "cukup pelaporan dulu, belum gate").
    report_only: bool = False
    # Whether this slice CAN be synthesized from generic image augmentation
    # (dark/blur/low-res/simple mask overlay) or genuinely requires real
    # human subjects with the actual condition (masked-riil, hijab,
    # kacamata, per-demografi, kontak kosmetik) - see task brief's realistic
    # scope note. `False` slices stay skeleton-only until EC-OPS-02.
    synthesizable: bool = False


SLICE_CATALOG: dict[str, SliceSpec] = {
    "masked-riil": SliceSpec(
        name="masked-riil",
        description="Real subjects wearing an actual mask (surgical/cloth) - "
        "the gate for ASM-EC-04 (synthetic-mask representativeness claim).",
        is_gate=True,
        synthesizable=False,
    ),
    "masked-sintetis": SliceSpec(
        name="masked-sintetis",
        description="MaskTheFace-style synthetic mask overlay on enrollment "
        "frames (A-4/EC-TR-02 template source).",
        is_gate=False,
        synthesizable=True,
    ),
    "dark": SliceSpec(
        name="dark",
        description="Low-light / dark condition (mean-luma ROI degraded).",
        is_gate=True,
        synthesizable=True,
    ),
    "kacamata": SliceSpec(
        name="kacamata",
        description="Subjects wearing prescription glasses (non-tinted).",
        is_gate=False,
        synthesizable=False,
    ),
    "hijab": SliceSpec(
        name="hijab",
        description="Subjects wearing a hijab (occludes hairline/ears, not "
        "the lower/mid face - distinct failure mode from masking).",
        is_gate=True,
        synthesizable=False,
    ),
    "blur": SliceSpec(
        name="blur",
        description="Motion/focus blur (camera or subject movement).",
        is_gate=False,
        synthesizable=True,
    ),
    "low-res": SliceSpec(
        name="low-res",
        description="Low-resolution capture (far-from-camera / downscaled sensor path).",
        is_gate=True,
        synthesizable=True,
    ),
    "per-demografi-utama": SliceSpec(
        name="per-demografi-utama",
        description="Primary demographic sub-groups (bias/audit reporting, REC 12.1/12.3).",
        is_gate=True,
        synthesizable=False,
    ),
    "masked-x-demografi": SliceSpec(
        name="masked-x-demografi",
        description="Interaction slice: masked probes crossed with "
        "demographic sub-group (R-4/REV - Mask-up finding that masked "
        "degradation is uneven across demographics). Report-only for now.",
        is_gate=False,
        report_only=True,
        synthesizable=False,
    ),
    "kontak-kosmetik": SliceSpec(
        name="kontak-kosmetik",
        description="Cosmetic/colored contact lenses. 5-10 samples = smoke "
        "test (ASM-EC-11) - never a gate, not statistically significant.",
        is_gate=False,
        is_smoke_test=True,
        synthesizable=False,
    ),
}


class RuleOf30Report(BaseModel):
    """OQ-8 composition check result for one slice manifest."""

    slice_name: str
    genuine_identity_count: int
    genuine_probe_count: int
    impostor_comparison_count: int
    genuine_identity_count_ok: bool
    genuine_probe_count_ok: bool
    impostor_comparison_count_ok: bool
    is_smoke_test_exempt: bool
    passes: bool
    notes: str = ""


MIN_GENUINE_IDENTITIES = 30
MIN_GENUINE_PROBES_PER_IDENTITY = 20
MIN_GENUINE_DECISIONS = 600  # 30 * 20, the "or" floor per OQ-8
IDEAL_GENUINE_DECISIONS = 1000
MIN_IMPOSTOR_COMPARISONS = 10_000


def check_rule_of_30(
    slice_name: str,
    *,
    genuine_identity_count: int,
    genuine_probe_count: int,
    impostor_comparison_count: int,
) -> RuleOf30Report:
    """OQ-8 "rule of 30" (NIST/ISO 19795) composition check.

    `genuine_probe_count_ok` accepts EITHER the strict per-identity floor
    (>= 30 identities x >= 20 probes) OR the aggregate decision floor (>=
    600 total genuine decisions) - TSD-EC D-7.2 explicitly allows
    compensating with more probes per identity when internal identity count
    is limited ("~30-50"), AS LONG AS the CI is reported (that's
    `ai_training.evaluation.stats`'s job, not this function's).
    """
    spec = SLICE_CATALOG.get(slice_name)
    is_smoke_test = bool(spec and spec.is_smoke_test)

    identity_ok = genuine_identity_count >= MIN_GENUINE_IDENTITIES
    probe_ok = genuine_probe_count >= MIN_GENUINE_DECISIONS
    impostor_ok = impostor_comparison_count >= MIN_IMPOSTOR_COMPARISONS

    passes = is_smoke_test or (identity_ok and probe_ok and impostor_ok)
    notes = (
        "smoke test (OQ-8/ASM-EC-11) - not held to rule-of-30, reported only"
        if is_smoke_test
        else ""
    )

    return RuleOf30Report(
        slice_name=slice_name,
        genuine_identity_count=genuine_identity_count,
        genuine_probe_count=genuine_probe_count,
        impostor_comparison_count=impostor_comparison_count,
        genuine_identity_count_ok=identity_ok,
        genuine_probe_count_ok=probe_ok,
        impostor_comparison_count_ok=impostor_ok,
        is_smoke_test_exempt=is_smoke_test,
        passes=passes,
        notes=notes,
    )


class SliceManifest(BaseModel):
    """Versioned/frozen manifest for one benchmark slice (TSD-EC D-7.2).

    `media` follows `ai_training.data.snapshots.MediaEntry` exactly (same
    S3-reference-only contract) plus a `condition_flags` sidecar per entry
    is intentionally NOT modeled here yet - EC-BE-02's
    `face_embeddings.masked`/`media_objects.variant` columns are the source
    of truth for condition flags once real capture exists; this manifest
    only needs to know WHICH media belong to the slice and their true
    identity (for genuine) or `None` (for impostor-only entries), mirroring
    `DatasetSnapshot`.
    """

    slice_name: str
    version: str
    category: str = ""
    is_gate: bool = False
    is_smoke_test: bool = False
    report_only: bool = False
    # "synthetic_placeholder" (this task's proof-of-concept scale data,
    # regenerable from `generation` below - see
    # ai_training.evaluation.synthetic_slices) | "awaiting_real_data"
    # (skeleton only, EC-OPS-02 not yet run) | "real" (EC-OPS-02 delivered).
    data_status: str = "awaiting_real_data"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Present only for data_status == "synthetic_placeholder": records HOW
    # to regenerate the exact same pixel data deterministically, so no
    # synthetic image bytes need to be persisted anywhere (local disk OR
    # S3) to keep this manifest reproducible - see
    # `ai_training.evaluation.synthetic_slices` module docstring.
    generation: dict[str, Any] = Field(default_factory=dict)
    genuine_identity_count: int = 0
    genuine_probe_count: int = 0
    impostor_comparison_count: int = 0
    media: list[MediaEntry] = Field(default_factory=list)
    notes: str = ""

    def rule_of_30(self) -> RuleOf30Report:
        return check_rule_of_30(
            self.slice_name,
            genuine_identity_count=self.genuine_identity_count,
            genuine_probe_count=self.genuine_probe_count,
            impostor_comparison_count=self.impostor_comparison_count,
        )


_BENCHMARK_PREFIX = "benchmarks/edge-cases"


def slice_manifest_key(slice_name: str, version: str) -> str:
    """`s3://{bucket}/benchmarks/edge-cases/{slice_name}/{version}/manifest.json`
    - the convention named in the EC-TR-01 task brief, mirroring
    `ai_training.data.snapshots._manifest_key`'s
    `datasets/{snapshot_id}/manifest.json`."""
    return f"{_BENCHMARK_PREFIX}/{slice_name}/{version}/manifest.json"


def save_slice_manifest(
    settings: Settings, manifest: SliceManifest, *, s3_client: Any = None
) -> None:
    """Upload a frozen/versioned slice manifest to S3.

    Same injection-point convention as `ai_training.data.snapshots.build_snapshot`:
    tests pass a mock/fake `s3_client`, production leaves it `None` and gets
    a real `boto3` client. Uploading the SAME `(slice_name, version)` twice
    silently overwrites - callers that want true immutability (TSD-EC D-7.2
    "beku di S3") must mint a new `version` string per freeze, the same
    discipline `snapshots.py` documents for `snapshot_id`.
    """
    from ai_training.storage import build_s3_client

    client = s3_client if s3_client is not None else build_s3_client(settings)
    client.put_object(
        Bucket=settings.s3.bucket,
        Key=slice_manifest_key(manifest.slice_name, manifest.version),
        Body=manifest.model_dump_json(indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def load_slice_manifest(
    settings: Settings, slice_name: str, version: str, *, s3_client: Any = None
) -> SliceManifest:
    """Read back a manifest previously written by `save_slice_manifest`."""
    from ai_training.storage import build_s3_client

    client = s3_client if s3_client is not None else build_s3_client(settings)
    response = client.get_object(
        Bucket=settings.s3.bucket, Key=slice_manifest_key(slice_name, version)
    )
    body = response["Body"].read()
    return SliceManifest.model_validate_json(body)


def skeleton_manifest(slice_name: str, version: str = "v0-skeleton") -> SliceManifest:
    """Build the (unpopulated) contract manifest for a slice that needs real
    human-subject data not yet collected (EC-OPS-02) - "skeleton/kontrak
    data ... TANPA data isi" per the task brief. `media` stays empty;
    `genuine_identity_count` etc. stay 0, so `rule_of_30()` correctly
    reports `passes=False` (or `passes=True` only if the slice happens to be
    a smoke test) until real media is attached."""
    spec = SLICE_CATALOG[slice_name]
    return SliceManifest(
        slice_name=slice_name,
        version=version,
        category=slice_name,
        is_gate=spec.is_gate,
        is_smoke_test=spec.is_smoke_test,
        report_only=spec.report_only,
        data_status="awaiting_real_data",
        notes=f"Skeleton contract only - awaiting EC-OPS-02 real-subject collection "
        f"for slice '{slice_name}'. {spec.description}",
    )
