"""TR-03 best-frame selection — plain dataclasses, no cv2 dependency."""

from dataclasses import dataclass

from ai_training.embedding.sampling import select_best_frames


@dataclass
class DummyCandidate:
    blur: float
    passed: bool
    label: str


def test_select_best_frames_prefers_passing_and_sharper() -> None:
    candidates = [
        DummyCandidate(blur=10.0, passed=True, label="a"),
        DummyCandidate(blur=90.0, passed=True, label="b"),
        DummyCandidate(blur=200.0, passed=False, label="c"),  # sharper but failed QC
    ]
    best = select_best_frames(candidates, k=1)
    assert [c.label for c in best] == ["b"]


def test_select_best_frames_falls_back_when_none_passed() -> None:
    candidates = [
        DummyCandidate(blur=10.0, passed=False, label="a"),
        DummyCandidate(blur=90.0, passed=False, label="b"),
    ]
    best = select_best_frames(candidates, k=1)
    assert [c.label for c in best] == ["b"]


def test_select_best_frames_respects_k() -> None:
    candidates = [DummyCandidate(blur=float(i), passed=True, label=str(i)) for i in range(5)]
    best = select_best_frames(candidates, k=3)
    assert [c.label for c in best] == ["4", "3", "2"]
