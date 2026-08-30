"""Gallery embedding extraction orchestration (TR-03, FR-ENR-07).

Given the per-clock-position frames already decoded/evaluated by TR-02's
`ai_training.quality.pipeline.run_quality_check`, this:

1. selects the best K frames per pose bucket (`embedding.sampling`),
2. detects landmarks + aligns each to a standard 112x112 crop
   (`embedding.alignment`),
3. embeds each aligned crop with the configured `EmbedderInterface`
   (`embedding.embedder` — `StubEmbedder` today),
4. averages + re-normalizes the per-bucket embeddings into ONE template
   vector per pose bucket (recommendations.md §4 step 6).

Real plumbing end-to-end; the embedding VALUES are only as real as the
injected `embedder` (a placeholder until AdaFace is procured — see
`embedding/embedder.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_training.embedding.alignment import align_face
from ai_training.embedding.embedder import EmbedderInterface
from ai_training.embedding.sampling import select_best_frames
from ai_training.quality.pose import detect_face_and_landmarks

if TYPE_CHECKING:
    from ai_training.quality.pipeline import FrameQuality


@dataclass(frozen=True)
class PoseBucketEmbedding:
    pose_bucket: str
    vector: list[float]
    model_version: str


def extract_gallery_embeddings(
    frames_by_position: dict[str, list[FrameQuality]],
    embedder: EmbedderInterface,
    *,
    frames_per_bucket: int = 3,
) -> list[PoseBucketEmbedding]:
    """Build one gallery template embedding per pose bucket that has at
    least one usable frame. Buckets with zero usable frames are skipped
    (not zero-filled) — a partially-covered gallery is expected to be rare
    given TR-02's coverage gate, but is not itself an error at this layer.
    """
    import numpy as np

    templates: list[PoseBucketEmbedding] = []
    for position, candidates in frames_by_position.items():
        if not candidates:
            continue
        best = select_best_frames(candidates, k=frames_per_bucket)

        vectors: list[list[float]] = []
        for candidate in best:
            detection = detect_face_and_landmarks(candidate.frame)
            if detection is None:
                continue  # extremely unlikely (already detected once in QC) but not fatal
            aligned = align_face(candidate.frame, detection.alignment_landmarks_5pt())
            vectors.append(embedder.embed(aligned))

        if not vectors:
            continue

        mean_vector = np.asarray(vectors, dtype=np.float64).mean(axis=0)
        norm = np.linalg.norm(mean_vector)
        if norm > 0:
            mean_vector = mean_vector / norm
        templates.append(
            PoseBucketEmbedding(
                pose_bucket=position,
                vector=[float(x) for x in mean_vector],
                model_version=embedder.model_version,
            )
        )
    return templates
