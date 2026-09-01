"""face_embeddings partial HNSW index on masked=true (EC-IN-04,
TSD-edge-cases.md D-4.1/D-4.2, task acceptance criteria: filter overhead
<2ms)

`ai_inference.gallery.search_top_k`'s new `masked` filter (EC-IN-04) adds
`AND masked = %s` to the ANN query when the caller's probe is flagged
`masked` (dual-mode decision path, `Settings.dual_mode_threshold_enabled`).
The existing `ix_face_embeddings_vector_hnsw_cosine` index (baseline
schema) covers the WHOLE table -- a `masked = true` filter on top of it
would either force a post-index-scan recheck over a much larger candidate
set than necessary, or (worse, depending on the planner/pgvector version)
fall back to a sequential scan, neither of which is within the <2ms filter
overhead this task's acceptance criteria requires.

A dedicated **partial** HNSW index restricted to `masked = true` rows keeps
the ANN search for masked probes scoped to ONLY the masked-template subset
of the gallery (2-3 `synthetic_masked` templates per enrolled user, per
A-4/D-4.5 -- a small fraction of the ~13 templates/user in the full,
unfiltered index), so `masked=true` queries hit a small, purpose-built index
instead of filtering down from the full one. This is purely additive: the
original `ix_face_embeddings_vector_hnsw_cosine` index is untouched and
still used for the default (`masked=None`, unfiltered) query path -- the
overwhelming majority of `/recognize` traffic (`dual_mode_threshold_enabled`
defaults to `False`, and even when enabled most probes are NOT flagged
`masked`).

Revision ID: e1f9b3c7a2d5
Revises: c7d4b1a9e3f6
Create Date: 2026-09-01 15:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f9b3c7a2d5"
down_revision: str | None = "d8e1f3a6c2b5"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_face_embeddings_vector_hnsw_cosine_masked "
        "ON face_embeddings USING hnsw (vector vector_cosine_ops) "
        "WHERE masked = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_face_embeddings_vector_hnsw_cosine_masked")
