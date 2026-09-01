"""Repository layer — data access (SQLAlchemy). Populated from task BE-02 onward."""

from app.repositories.audit_logs import AuditLogRepository
from app.repositories.devices import DeviceRepository
from app.repositories.identity_similarity_flags import IdentitySimilarityFlagRepository
from app.repositories.recognition_configs import RecognitionConfigRepository
from app.repositories.users import UserRepository

__all__ = [
    "AuditLogRepository",
    "DeviceRepository",
    "IdentitySimilarityFlagRepository",
    "RecognitionConfigRepository",
    "UserRepository",
]
