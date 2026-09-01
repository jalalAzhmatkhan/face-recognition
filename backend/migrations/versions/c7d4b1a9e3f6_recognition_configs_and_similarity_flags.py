"""recognition_configs + identity_similarity_flags (EC-BE-04,
TSD-edge-cases.md D-4.2/D-4.4/D-10, OQ-6)

Two brand-new, additive tables — no existing table/column is touched.

`recognition_configs`:
  - `scope` (NOT NULL, new native enum `recognition_config_scope`:
    `global|device_class|user`) + `scope_ref` (nullable varchar(64)) +
    `mode` (NOT NULL varchar(32)) form the override KEY. Per OQ-6, this
    table is a POLICY OVERRIDE on top of the per-mode default that lives as
    MLflow model-artefact metadata — see
    app/models/recognition_config.py and
    app/services/recognition_config_service.py for the full resolution
    contract.
  - `similarity_threshold`/`margin`/`liveness_threshold`/`min_frames` are
    all nullable — NULL on a given field means "not overridden", not
    "zero".
  - `created_by_staff_id` is NOT NULL (every row is created through the
    ADMIN-only CRUD endpoint, which always has an authenticated actor) with
    `ondelete="RESTRICT"` — same convention as `training_jobs.triggered_by`
    (never let deleting a staff account silently orphan/cascade-delete
    audit-relevant config history).
  - Two PARTIAL unique indexes (NOT one `UniqueConstraint`) enforce "at
    most one row per (scope, scope_ref, mode)": a plain multi-column unique
    constraint would not catch two `GLOBAL` rows for the same `mode`, since
    SQL NULLs (scope_ref is always NULL for GLOBAL) never compare equal to
    each other. `ix_recognition_configs_scoped_key` covers
    DEVICE_CLASS/USER rows (`scope_ref IS NOT NULL`);
    `ix_recognition_configs_global_key` covers GLOBAL rows
    (`scope_ref IS NULL`) on `(scope, mode)` alone.
  - A CHECK constraint (`ck_recognition_configs_scope_ref_matches_scope`)
    backstops the Pydantic-level validation in
    `RecognitionConfigCreateRequest` that `scope='global'` <=> `scope_ref
    IS NULL`.

`identity_similarity_flags` (D-4.4): high-similarity pairs between two
distinct enrolled identities, written by a later ai-training pipeline task
(TR-03/GALLERY_REEMBED), not by this migration's own endpoints. `user_a_id`/
`user_b_id` both FK `users.id` `ondelete="CASCADE"` (mirrors
`face_embeddings.user_id`/`access_policies.user_id` — a flag about a user
that no longer exists in the identity table is meaningless, so it is
removed along with the user rather than orphaned). A CHECK constraint
prevents a degenerate self-pair.

`ai_inference_ro` (migration `b7c4e1a2d9f0`) is additionally granted SELECT
on `recognition_configs` here: `/recognize`'s decision path (a later
EC-IN-04 task) is the actual reader of this table's overrides at inference
time, and `ai_inference_ro` has no `ALTER DEFAULT PRIVILEGES` grant (unlike
`ai_training_ro`), so a brand-new table is invisible to it unless granted
explicitly. `identity_similarity_flags` is NOT granted to `ai_inference_ro`
here — nothing in the current `/recognize` decision path (D-4/D-6) reads it
directly; only the offline adaptive-template job (D-6, a later task) does,
which is ai-training's role, not ai-inference's.

Revision ID: c7d4b1a9e3f6
Revises: b3f7c2a1d9e4
Create Date: 2026-09-01 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c7d4b1a9e3f6"
down_revision: str | None = "b3f7c2a1d9e4"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

RECOGNITION_CONFIG_SCOPE = postgresql.ENUM(
    "global",
    "device_class",
    "user",
    name="recognition_config_scope",
    create_type=False,
)

AI_INFERENCE_RO_ROLE = "ai_inference_ro"


def upgrade() -> None:
    bind = op.get_bind()
    RECOGNITION_CONFIG_SCOPE.create(bind, checkfirst=True)

    op.create_table(
        "recognition_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", RECOGNITION_CONFIG_SCOPE, nullable=False),
        sa.Column("scope_ref", sa.String(length=64), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("similarity_threshold", sa.Float(), nullable=True),
        sa.Column("margin", sa.Float(), nullable=True),
        sa.Column("liveness_threshold", sa.Float(), nullable=True),
        sa.Column("min_frames", sa.Integer(), nullable=True),
        sa.Column(
            "created_by_staff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("staff_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(scope = 'global' AND scope_ref IS NULL) OR "
            "(scope IN ('device_class', 'user') AND scope_ref IS NOT NULL)",
            name="ck_recognition_configs_scope_ref_matches_scope",
        ),
    )
    op.create_index(
        "ix_recognition_configs_scoped_key",
        "recognition_configs",
        ["scope", "scope_ref", "mode"],
        unique=True,
        postgresql_where=sa.text("scope_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_recognition_configs_global_key",
        "recognition_configs",
        ["scope", "mode"],
        unique=True,
        postgresql_where=sa.text("scope_ref IS NULL"),
    )
    op.create_index(
        "ix_recognition_configs_created_by_staff_id",
        "recognition_configs",
        ["created_by_staff_id"],
    )

    op.create_table(
        "identity_similarity_flags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_a_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_b_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "flagged_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "user_a_id <> user_b_id", name="ck_identity_similarity_flags_distinct"
        ),
    )
    op.create_index(
        "ix_identity_similarity_flags_user_a_id",
        "identity_similarity_flags",
        ["user_a_id"],
    )
    op.create_index(
        "ix_identity_similarity_flags_user_b_id",
        "identity_similarity_flags",
        ["user_b_id"],
    )

    # See module docstring: ai_inference_ro has no ALTER DEFAULT PRIVILEGES
    # grant, so a new table must be granted explicitly for /recognize's
    # (later, EC-IN-04) decision path to be able to read overrides.
    op.execute(f"GRANT SELECT ON recognition_configs TO {AI_INFERENCE_RO_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON recognition_configs FROM {AI_INFERENCE_RO_ROLE}")

    op.drop_index("ix_identity_similarity_flags_user_b_id", table_name="identity_similarity_flags")
    op.drop_index("ix_identity_similarity_flags_user_a_id", table_name="identity_similarity_flags")
    op.drop_table("identity_similarity_flags")

    op.drop_index("ix_recognition_configs_created_by_staff_id", table_name="recognition_configs")
    op.drop_index(
        "ix_recognition_configs_global_key",
        table_name="recognition_configs",
        postgresql_where=sa.text("scope_ref IS NULL"),
    )
    op.drop_index(
        "ix_recognition_configs_scoped_key",
        table_name="recognition_configs",
        postgresql_where=sa.text("scope_ref IS NOT NULL"),
    )
    op.drop_table("recognition_configs")

    bind = op.get_bind()
    RECOGNITION_CONFIG_SCOPE.drop(bind, checkfirst=True)
