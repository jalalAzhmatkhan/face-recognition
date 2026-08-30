"""models — model registry / promotion lifecycle (TSD §4, FR-TRN-05).

Named `model_registry.py` (not `model.py`) to avoid confusion with the
`app/models/` package itself; the table name stays `models` per TSD §4.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ModelStage


class ModelVersion(Base):
    __tablename__ = "models"

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    mlflow_run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[ModelStage] = mapped_column(
        Enum(ModelStage, name="model_stage", native_enum=True),
        nullable=False,
        default=ModelStage.CANDIDATE,
        server_default=ModelStage.CANDIDATE.value,
    )
    # Priority order per CLAUDE.md/TSD §5: Recall (primary) -> F1 -> Precision.
    recall: Mapped[float | None] = mapped_column(Float)
    f1: Mapped[float | None] = mapped_column(Float)
    precision: Mapped[float | None] = mapped_column(Float)
    latency_ms_p95: Mapped[int | None] = mapped_column(Integer)
    promoted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_accounts.id", ondelete="SET NULL")
    )
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
