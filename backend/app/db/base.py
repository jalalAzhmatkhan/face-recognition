"""Declarative base shared by every ORM model (app/models/*)."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models in this service."""
