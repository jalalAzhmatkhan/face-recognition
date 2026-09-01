"""Gallery/probe split rule on top of a TR-04 snapshot (TR-07).

Pure - builds a `DatasetSnapshot` in memory, no S3/Postgres. See
`ai_training.evaluation.metrics` module docstring for the split rule.
"""

from __future__ import annotations

from ai_training.data.snapshots import DatasetSnapshot, MediaEntry
from ai_training.evaluation.metrics import _split_gallery_and_probes


def _entry(key: str, user_id: str | None) -> MediaEntry:
    session_id = f"session-{key}" if user_id is not None else None
    return MediaEntry(s3_key=key, kind="image", user_id=user_id, session_id=session_id)


def test_split_identity_with_two_media_becomes_one_gallery_one_genuine_probe() -> None:
    snapshot = DatasetSnapshot(
        snapshot_id="snap-1",
        media=[_entry("a1", "alice"), _entry("a2", "alice")],
    )

    gallery, probes = _split_gallery_and_probes(snapshot, gallery_media_per_identity=1)

    assert list(gallery.keys()) == ["alice"]
    assert [e.s3_key for e in gallery["alice"]] == ["a1"]
    assert [p[0] for p in probes] == ["alice"]
    assert [p[1].s3_key for p in probes] == ["a2"]


def test_split_identity_with_single_media_becomes_impostor_probe() -> None:
    snapshot = DatasetSnapshot(snapshot_id="snap-2", media=[_entry("b1", "bob")])

    gallery, probes = _split_gallery_and_probes(snapshot, gallery_media_per_identity=1)

    assert gallery == {}
    assert len(probes) == 1
    true_identity, entry = probes[0]
    assert true_identity is None
    assert entry.s3_key == "b1"


def test_split_gallery_media_per_identity_capped_to_leave_one_probe() -> None:
    # Only 2 media total but gallery_media_per_identity requests 5 -> must
    # be capped at len(media) - 1 == 1, so at least one probe remains.
    snapshot = DatasetSnapshot(
        snapshot_id="snap-3",
        media=[_entry("c1", "carol"), _entry("c2", "carol")],
    )

    gallery, probes = _split_gallery_and_probes(snapshot, gallery_media_per_identity=5)

    assert len(gallery["carol"]) == 1
    assert len(probes) == 1


def test_split_multiple_identities_are_independent() -> None:
    snapshot = DatasetSnapshot(
        snapshot_id="snap-4",
        media=[
            _entry("a1", "alice"),
            _entry("a2", "alice"),
            _entry("a3", "alice"),
            _entry("b1", "bob"),
        ],
    )

    gallery, probes = _split_gallery_and_probes(snapshot, gallery_media_per_identity=1)

    assert [e.s3_key for e in gallery["alice"]] == ["a1"]
    genuine_probes = [(t, e.s3_key) for t, e in probes if t is not None]
    impostor_probes = [(t, e.s3_key) for t, e in probes if t is None]
    assert genuine_probes == [("alice", "a2"), ("alice", "a3")]
    assert impostor_probes == [(None, "b1")]


def test_split_never_groups_two_unmatched_event_frame_entries_together() -> None:
    """EC-TR-05 regression: two `source=event_frame` probes that were each
    never matched to an identity both have `user_id=None` - naively keying
    `by_identity` on that shared `None` would bucket them as if they were
    one person's two media (and, once >=2, wrongly promote them into a
    single fabricated gallery identity instead of two separate impostor
    probes)."""
    snapshot = DatasetSnapshot(
        snapshot_id="snap-5",
        media=[_entry("e1", None), _entry("e2", None)],
    )

    gallery, probes = _split_gallery_and_probes(snapshot, gallery_media_per_identity=1)

    assert gallery == {}
    assert sorted(e.s3_key for _, e in probes) == ["e1", "e2"]
    assert all(true_identity is None for true_identity, _ in probes)
