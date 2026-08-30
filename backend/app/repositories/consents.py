"""Repository for `consents` (BE-05, FR-ENR-08).

Versioned consent records are append-only from this API's point of view in
BE-05 scope (create + read); revocation of consent itself is not part of
this task.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.consent import Consent


class ConsentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, consent_id: uuid.UUID) -> Consent | None:
        return self._session.get(Consent, consent_id)

    def list_for_user(self, user_id: uuid.UUID) -> list[Consent]:
        stmt = select(Consent).where(Consent.user_id == user_id).order_by(Consent.granted_at)
        return list(self._session.scalars(stmt))

    def create(self, consent: Consent) -> Consent:
        self._session.add(consent)
        self._session.commit()
        self._session.refresh(consent)
        return consent
