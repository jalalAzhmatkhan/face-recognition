"""`ai_training.embedding.synthetic_masked` (A-4, TSD-edge-cases.md A-4/OQ-1)
against a fake `MaskOverlayProvider` + `StubEmbedder` -- never real
dlib/MaskTheFace/cv2/mediapipe, per project testing convention (mirrors
test_gallery_reembed.py's monkeypatch-the-heavy-pieces approach)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_training.embedding.embedder import StubEmbedder
from ai_training.embedding.synthetic_masked import (
    SOURCE_YAW_TARGETS,
    generate_synthetic_masked_templates,
    select_masked_source_frames,
)
from ai_training.quality.mask_overlay import MASK_TYPES


@dataclass
class FakeFrame:
    """Minimal `FrameQuality`-shaped stand-in (only the fields
    `select_masked_source_frames`/`generate_synthetic_masked_templates`
    actually read) -- a real `FrameQuality` needs a genuine numpy BGR
    frame + cv2 to construct meaningfully, which this module has no need
    of; a plain marker object stands in for `frame` here."""

    frame: Any
    position: str
    blur: float
    yaw: float
    passed: bool = True


class FakeMaskOverlayProvider:
    """Records every `apply()` call; returns a deterministic "masked
    frame" marker so downstream detect/align/embed can be monkeypatched
    to succeed."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, str]] = []

    def apply(self, frame_bgr: Any, mask_type: str) -> Any:
        self.calls.append((frame_bgr, mask_type))
        return ("masked", frame_bgr, mask_type)


class AlwaysFailingMaskOverlayProvider:
    def apply(self, frame_bgr: Any, mask_type: str) -> Any:
        raise RuntimeError("dlib is not installed (simulated)")


class ReturnsNoneMaskOverlayProvider:
    def apply(self, frame_bgr: Any, mask_type: str) -> Any | None:
        return None


def _frames_by_position(*frames: FakeFrame) -> dict[str, list[FakeFrame]]:
    by_position: dict[str, list[FakeFrame]] = {}
    for frame in frames:
        by_position.setdefault(frame.position, []).append(frame)
    return by_position


def _patch_detect_and_align(monkeypatch, *, detection_succeeds: bool = True) -> None:
    class FakeDetection:
        def alignment_landmarks_5pt(self) -> list[float]:
            return [0.0]

    monkeypatch.setattr(
        "ai_training.embedding.synthetic_masked.detect_face_and_landmarks",
        lambda frame: (FakeDetection() if detection_succeeds else None),
    )
    monkeypatch.setattr(
        "ai_training.embedding.synthetic_masked.align_face",
        lambda frame, landmarks: "aligned-crop",
    )


# --- select_masked_source_frames ------------------------------------------


def test_selects_frontal_and_plus_minus_30_yaw() -> None:
    frontal = FakeFrame(frame="f0", position="12", blur=100.0, yaw=0.0)
    plus30 = FakeFrame(frame="f30", position="02", blur=100.0, yaw=31.0)
    minus30 = FakeFrame(frame="f-30", position="10", blur=100.0, yaw=-29.0)
    irrelevant_profile = FakeFrame(frame="fprofile", position="03", blur=200.0, yaw=80.0)

    selected = select_masked_source_frames(
        _frames_by_position(frontal, plus30, minus30, irrelevant_profile)
    )

    assert [s.yaw for s in selected] == [0.0, 31.0, -29.0]
    assert SOURCE_YAW_TARGETS == (0.0, 30.0, -30.0)


def test_does_not_reuse_the_same_frame_for_multiple_targets() -> None:
    only_frame = FakeFrame(frame="f0", position="12", blur=100.0, yaw=5.0)

    selected = select_masked_source_frames(_frames_by_position(only_frame))

    # Only one usable frame exists -- it is picked once (for the closest
    # target, frontal), not duplicated across all 3 targets.
    assert selected == [only_frame]


def test_prefers_passing_frames_but_falls_back_when_none_passed() -> None:
    failing = FakeFrame(frame="f0", position="12", blur=100.0, yaw=0.0, passed=False)

    selected = select_masked_source_frames(_frames_by_position(failing))

    assert selected == [failing]


def test_no_usable_frames_returns_empty_list() -> None:
    assert select_masked_source_frames({}) == []


# --- generate_synthetic_masked_templates ----------------------------------


def test_generates_one_template_per_source_frame_with_round_robin_mask_types(monkeypatch) -> None:
    _patch_detect_and_align(monkeypatch)
    frames = _frames_by_position(
        FakeFrame(frame="f0", position="12", blur=100.0, yaw=0.0),
        FakeFrame(frame="f30", position="02", blur=100.0, yaw=30.0),
        FakeFrame(frame="f-30", position="10", blur=100.0, yaw=-30.0),
    )
    provider = FakeMaskOverlayProvider()
    embedder = StubEmbedder(version="stub-test")

    templates = generate_synthetic_masked_templates(frames, embedder, provider, session_id="s1")

    assert len(templates) == 3
    assert [t.mask_type for t in templates] == [MASK_TYPES[0], MASK_TYPES[1], MASK_TYPES[0]]
    assert [t.pose_bucket for t in templates] == ["12", "02", "10"]
    assert all(t.model_version == "stub-test" for t in templates)
    assert len(provider.calls) == 3


def test_provider_failure_degrades_to_fewer_templates_not_an_exception(monkeypatch) -> None:
    """The core graceful-degradation guarantee: an overlay provider that
    always raises (e.g. MaskTheFaceProvider without dlib installed, see
    ai_training.quality.mask_overlay) must never propagate out of this
    function -- callers get back an empty list, not an exception."""
    _patch_detect_and_align(monkeypatch)
    frames = _frames_by_position(FakeFrame(frame="f0", position="12", blur=100.0, yaw=0.0))
    provider = AlwaysFailingMaskOverlayProvider()
    embedder = StubEmbedder()

    templates = generate_synthetic_masked_templates(frames, embedder, provider, session_id="s1")

    assert templates == []


def test_provider_returning_none_is_skipped_not_an_error(monkeypatch) -> None:
    _patch_detect_and_align(monkeypatch)
    frames = _frames_by_position(FakeFrame(frame="f0", position="12", blur=100.0, yaw=0.0))
    provider = ReturnsNoneMaskOverlayProvider()
    embedder = StubEmbedder()

    templates = generate_synthetic_masked_templates(frames, embedder, provider, session_id="s1")

    assert templates == []


def test_landmark_redetection_failure_on_masked_frame_is_skipped(monkeypatch) -> None:
    """A synthetic mask can occlude enough of the face that landmark
    re-detection on the MASKED frame fails -- this must be skipped, not
    fatal (and per TSD A-4, heavy-occlusion frames must never become a
    template)."""
    _patch_detect_and_align(monkeypatch, detection_succeeds=False)
    frames = _frames_by_position(FakeFrame(frame="f0", position="12", blur=100.0, yaw=0.0))
    provider = FakeMaskOverlayProvider()
    embedder = StubEmbedder()

    templates = generate_synthetic_masked_templates(frames, embedder, provider, session_id="s1")

    assert templates == []


def test_no_usable_source_frames_yields_no_templates(monkeypatch) -> None:
    _patch_detect_and_align(monkeypatch)
    provider = FakeMaskOverlayProvider()
    embedder = StubEmbedder()

    templates = generate_synthetic_masked_templates({}, embedder, provider, session_id="s1")

    assert templates == []
    assert provider.calls == []
