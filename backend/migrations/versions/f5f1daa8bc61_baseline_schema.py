"""baseline schema

Creates every table from TSD §4: users, staff_accounts, consents,
enrollment_sessions, media_objects, face_embeddings (pgvector, HNSW cosine
index), models, devices, access_policies, access_events (partitioned by
month), audit_logs (append-only — see the `db role separation` migration for
the DB-level UPDATE/DELETE restriction).

Revision ID: f5f1daa8bc61
Revises:
Create Date: 2026-08-30 15:46:13.358967

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f5f1daa8bc61"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

EMBEDDING_DIM = 512

# Enum type names <-> members, kept in sync with app/models/enums.py.
USER_STATUS = ("ACTIVE", "SUSPENDED", "OFFBOARDED")
STAFF_ROLE = ("ADMIN", "OPERATOR", "VIEWER")
ENROLLMENT_STATE = (
    "CREATED",
    "CONSENTED",
    "CAPTURING",
    "CAPTURED",
    "QC_RUNNING",
    "REJECTED_QUALITY",
    "QC_PASSED",
    "EMBEDDING",
    "ENROLLED",
    "CANCELLED",
    "REVOKED",
)
MEDIA_KIND = ("photo", "video", "event_frame")
MODEL_STAGE = ("CANDIDATE", "PRODUCTION", "RETIRED")
DEVICE_STATUS = ("ONLINE", "OFFLINE", "DISABLED")
ACCESS_DECISION = ("GRANTED", "DENIED", "SPOOF_SUSPECTED")

# First few monthly partitions created up front as a working example; add more
# with the same pattern (see backend/README.md "Access-events partitions").
INITIAL_ACCESS_EVENTS_PARTITIONS = [
    ("access_events_2026_08", "2026-08-01", "2026-09-01"),
    ("access_events_2026_09", "2026-09-01", "2026-10-01"),
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # `create_type=False` on every enum: the type is created/dropped explicitly
    # below (once), so create_table()/drop_table() must NOT also try to
    # auto-(re)create or auto-drop it — that would double-create/double-drop.
    user_status = postgresql.ENUM(*USER_STATUS, name="user_status", create_type=False)
    staff_role = postgresql.ENUM(*STAFF_ROLE, name="staff_role", create_type=False)
    enrollment_state = postgresql.ENUM(
        *ENROLLMENT_STATE, name="enrollment_state", create_type=False
    )
    media_kind = postgresql.ENUM(*MEDIA_KIND, name="media_kind", create_type=False)
    model_stage = postgresql.ENUM(*MODEL_STAGE, name="model_stage", create_type=False)
    device_status = postgresql.ENUM(*DEVICE_STATUS, name="device_status", create_type=False)
    access_decision = postgresql.ENUM(
        *ACCESS_DECISION, name="access_decision", create_type=False
    )
    bind = op.get_bind()
    for enum_type in (
        user_status,
        staff_role,
        enrollment_state,
        media_kind,
        model_stage,
        device_status,
        access_decision,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_ref", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column(
            "status",
            user_status,
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_users_external_ref", "users", ["external_ref"], unique=True)

    op.create_table(
        "staff_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", staff_role, nullable=False),
        sa.Column("oidc_sub", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_staff_accounts_email", "staff_accounts", ["email"], unique=True)
    op.create_index("ix_staff_accounts_oidc_sub", "staff_accounts", ["oidc_sub"], unique=True)

    op.create_table(
        "consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("consent_version", sa.String(50), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_consents_user_id", "consents", ["user_id"])

    op.create_table(
        "enrollment_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "state",
            enrollment_state,
            nullable=False,
            server_default="CREATED",
        ),
        sa.Column("qc_report", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("staff_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_enrollment_sessions_user_id", "enrollment_sessions", ["user_id"])

    op.create_table(
        "media_objects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enrollment_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", media_kind, nullable=False),
        sa.Column("s3_bucket", sa.String(255), nullable=False),
        sa.Column("s3_key", sa.String(1024), nullable=False),
        sa.Column("checksum", sa.String(128), nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_media_objects_session_id", "media_objects", ["session_id"])

    op.create_table(
        "models",
        sa.Column("version", sa.String(64), primary_key=True),
        sa.Column("mlflow_run_id", sa.String(255), nullable=False),
        sa.Column(
            "stage",
            model_stage,
            nullable=False,
            server_default="CANDIDATE",
        ),
        sa.Column("recall", sa.Float, nullable=True),
        sa.Column("f1", sa.Float, nullable=True),
        sa.Column("precision", sa.Float, nullable=True),
        sa.Column("latency_ms_p95", sa.Integer, nullable=True),
        sa.Column(
            "promoted_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("staff_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "face_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enrollment_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_version",
            sa.String(64),
            sa.ForeignKey("models.version", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("pose_bucket", sa.String(16), nullable=False),
        sa.Column("vector", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_face_embeddings_user_id", "face_embeddings", ["user_id"])
    op.create_index("ix_face_embeddings_model_version", "face_embeddings", ["model_version"])
    # HNSW index for cosine-similarity ANN search (TSD §4/§5, ANN search <= 10ms p95).
    op.execute(
        "CREATE INDEX ix_face_embeddings_vector_hnsw_cosine "
        "ON face_embeddings USING hnsw (vector vector_cosine_ops)"
    )

    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("door_group", sa.String(255), nullable=False),
        sa.Column("auth_credential_ref", sa.String(255), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            device_status,
            nullable=False,
            server_default="OFFLINE",
        ),
    )
    op.create_index("ix_devices_door_group", "devices", ["door_group"])

    op.create_table(
        "access_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("door_group", sa.String(255), nullable=False),
        sa.Column("allowed", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_access_policies_user_id", "access_policies", ["user_id"])
    op.create_index("ix_access_policies_group_id", "access_policies", ["group_id"])
    op.create_index("ix_access_policies_door_group", "access_policies", ["door_group"])

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("entity", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # access_events: native declarative RANGE partitioning by month on occurred_at.
    # Postgres requires the partition key to be part of every unique constraint,
    # hence the composite PK (id, occurred_at) instead of a bare id.
    op.execute(
        """
        CREATE TABLE access_events (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            device_id UUID NOT NULL REFERENCES devices (id) ON DELETE RESTRICT,
            decision access_decision NOT NULL,
            matched_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
            similarity DOUBLE PRECISION,
            liveness_score DOUBLE PRECISION,
            model_version VARCHAR(64) REFERENCES models (version) ON DELETE SET NULL,
            latency_ms INTEGER,
            frame_media_id UUID REFERENCES media_objects (id) ON DELETE SET NULL,
            PRIMARY KEY (id, occurred_at)
        ) PARTITION BY RANGE (occurred_at)
        """
    )
    op.create_index("ix_access_events_device_id", "access_events", ["device_id"])
    op.create_index("ix_access_events_matched_user_id", "access_events", ["matched_user_id"])

    # A couple of example partitions so the table is immediately usable in dev.
    # To add the next month's partition later, run (see backend/README.md):
    #   CREATE TABLE access_events_YYYY_MM PARTITION OF access_events
    #     FOR VALUES FROM ('YYYY-MM-01') TO ('YYYY-MM-01' next month);
    for name, start, end in INITIAL_ACCESS_EVENTS_PARTITIONS:
        op.execute(
            f"CREATE TABLE {name} PARTITION OF access_events "
            f"FOR VALUES FROM ('{start}') TO ('{end}')"
        )
    # Catch-all default partition so inserts outside the pre-created ranges
    # don't fail outright while automation for BE-14/ops adds real partitions.
    op.execute("CREATE TABLE access_events_default PARTITION OF access_events DEFAULT")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS access_events_default")
    for name, _start, _end in reversed(INITIAL_ACCESS_EVENTS_PARTITIONS):
        op.execute(f"DROP TABLE IF EXISTS {name}")
    op.drop_index("ix_access_events_matched_user_id", table_name="access_events")
    op.drop_index("ix_access_events_device_id", table_name="access_events")
    op.execute("DROP TABLE IF EXISTS access_events")

    op.drop_table("audit_logs")

    op.drop_index("ix_access_policies_door_group", table_name="access_policies")
    op.drop_index("ix_access_policies_group_id", table_name="access_policies")
    op.drop_index("ix_access_policies_user_id", table_name="access_policies")
    op.drop_table("access_policies")

    op.drop_index("ix_devices_door_group", table_name="devices")
    op.drop_table("devices")

    op.execute("DROP INDEX IF EXISTS ix_face_embeddings_vector_hnsw_cosine")
    op.drop_index("ix_face_embeddings_model_version", table_name="face_embeddings")
    op.drop_index("ix_face_embeddings_user_id", table_name="face_embeddings")
    op.drop_table("face_embeddings")

    op.drop_table("models")

    op.drop_index("ix_media_objects_session_id", table_name="media_objects")
    op.drop_table("media_objects")

    op.drop_index("ix_enrollment_sessions_user_id", table_name="enrollment_sessions")
    op.drop_table("enrollment_sessions")

    op.drop_index("ix_consents_user_id", table_name="consents")
    op.drop_table("consents")

    op.drop_index("ix_staff_accounts_oidc_sub", table_name="staff_accounts")
    op.drop_index("ix_staff_accounts_email", table_name="staff_accounts")
    op.drop_table("staff_accounts")

    op.drop_index("ix_users_external_ref", table_name="users")
    op.drop_table("users")

    bind = op.get_bind()
    for enum_name in (
        "access_decision",
        "device_status",
        "model_stage",
        "media_kind",
        "enrollment_state",
        "staff_role",
        "user_status",
    ):
        postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)

    op.execute("DROP EXTENSION IF EXISTS vector")
