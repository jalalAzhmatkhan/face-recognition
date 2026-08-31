"""SQLAlchemy ORM models for every table in TSD §4.

Importing this package registers all tables on `app.db.base.Base.metadata` —
required both by alembic autogenerate/`--sql` and by tests that assert the
schema builds without a live database.
"""

from app.db.base import Base
from app.models.access_event import AccessEvent
from app.models.access_policy import AccessPolicy
from app.models.audit_log import AuditLog
from app.models.consent import Consent
from app.models.device import Device
from app.models.enrollment_session import EnrollmentSession
from app.models.face_embedding import EMBEDDING_DIM, FaceEmbedding
from app.models.media_object import MediaObject
from app.models.model_registry import ModelVersion
from app.models.password_reset_token import PasswordResetToken
from app.models.staff_account import StaffAccount
from app.models.training_job import TrainingJob
from app.models.user import User

__all__ = [
    "Base",
    "AccessEvent",
    "AccessPolicy",
    "AuditLog",
    "Consent",
    "Device",
    "EnrollmentSession",
    "EMBEDDING_DIM",
    "FaceEmbedding",
    "MediaObject",
    "ModelVersion",
    "PasswordResetToken",
    "StaffAccount",
    "TrainingJob",
    "User",
]
