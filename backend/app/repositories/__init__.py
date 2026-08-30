"""Repository layer — data access (SQLAlchemy). Populated from task BE-02 onward."""

from app.repositories.users import UserRepository

__all__ = ["UserRepository"]
