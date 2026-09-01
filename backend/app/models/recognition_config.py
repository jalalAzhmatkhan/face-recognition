"""recognition_configs — policy OVERRIDE on top of the per-mode defaults
baked into a model artefact (EC-BE-04, TSD-edge-cases.md D-4.2/D-10, OQ-6).

This table is deliberately NOT the source of truth for recognition
thresholds. Per the TSD's OQ-6 decision, the actual default for a given
`mode` (e.g. `normal`/`masked`/`dark`) lives as METADATA on the MLflow model
artefact (embedder threshold/margin, liveness calibration curve) so a model
rollback atomically rolls back its calibrated defaults too. A row here is an
explicit, audited DELTA a staff ADMIN applies on top of that default for one
scope — e.g. "loosen the masked-mode similarity threshold for
`device_class='attendance'`" or "raise this one user's threshold after a
high-similarity flag (D-4.4)". Any column left NULL on a row means "this
field is not overridden here" — the caller falls through to the artefact
default, and ultimately to the `INF_SIMILARITY_THRESHOLD` env var as the
last-resort fallback (`ai-inference/config.py`). See
`app/services/recognition_config_service.py::resolve_recognition_config`
for the full 3-layer resolution contract.

`(scope, scope_ref, mode)` is the override key and must be unique — two rows
for the same key would make "the" override for that scope+mode ambiguous.
Because `scope_ref` is NULL for `GLOBAL` (there is exactly one global scope,
not one per NULL) a single `UniqueConstraint` cannot express this (SQL NULLs
compare distinct from each other), so uniqueness is enforced by two partial
unique indexes instead — see the EC-BE-04 migration.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import RecognitionConfigScope
from app.models.mixins import UUIDPKMixin


class RecognitionConfig(UUIDPKMixin, Base):
    __tablename__ = "recognition_configs"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'global' AND scope_ref IS NULL) OR "
            "(scope IN ('device_class', 'user') AND scope_ref IS NOT NULL)",
            name="ck_recognition_configs_scope_ref_matches_scope",
        ),
    )

    scope: Mapped[RecognitionConfigScope] = mapped_column(
        Enum(
            RecognitionConfigScope,
            name="recognition_config_scope",
            native_enum=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    # Holds the value `scope` keys on: NULL for GLOBAL, a
    # `devices.device_class` string for DEVICE_CLASS, a stringified
    # `users.id` UUID for USER. Deliberately a loose `String`, not a
    # `ForeignKey` — it points at two different tables depending on `scope`
    # (a polymorphic reference), which SQLAlchemy/Postgres cannot express as
    # a single FK constraint; validity is enforced at the service layer
    # (app/services/recognition_config_service.py) instead, same "loose FK"
    # convention as `training_jobs.model_version`/`snapshot_id`.
    scope_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Recognition "mode" this override applies to, e.g. `normal`/`masked`/
    # `dark` (TSD D-2/D-4 multi-mode threshold design). Deliberately a free
    # string, not a native enum: the TSD explicitly leaves the mode set
    # open-ended ("mis. normal|masked|dark dll") since it is calibrated per
    # model artefact, not fixed by the DB schema.
    mode: Mapped[str] = mapped_column(String(32), nullable=False)

    similarity_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    liveness_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_frames: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_by_staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staff_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"RecognitionConfig(id={self.id!r}, scope={self.scope!r}, "
            f"scope_ref={self.scope_ref!r}, mode={self.mode!r})"
        )
