"""Revocation cleanup job enqueue (BE-08).

Mirrors `app/services/qc_queue.py` exactly (see that module's docstring for
the full rationale): dispatch is best-effort so a Redis/broker outage never
fails the synchronous, security-critical part of revocation (state
transition to REVOKED + user OFFBOARDED, both already committed by the time
this is called). The endpoint still returns 202 — the physical
deletion/tombstone SLA (24h, FR-ENR-09/ASM-12) is met by re-dispatching this
job manually against sessions stuck in REVOKED with leftover
embeddings/media, same as the QC job's documented gap.
"""

import logging
import uuid

logger = logging.getLogger(__name__)


def enqueue_revocation_cleanup(session_id: uuid.UUID) -> None:
    """Enqueue the async revocation cleanup job for `session_id` (FR-ENR-09).

    Never raises: broker/connection errors are caught and logged so the
    caller (revocation_service.revoke_enrollment's committed transaction) is
    never affected by Redis/Celery availability.
    """
    try:
        from app.worker.tasks import revoke_enrollment_cleanup

        revoke_enrollment_cleanup.delay(str(session_id))
    except Exception:
        logger.exception(
            "revocation_queue.enqueue_revocation_cleanup: failed to dispatch "
            "revoke_enrollment_cleanup for session_id=%s (broker unavailable?) — "
            "embeddings/media/tombstone cleanup remains pending until the job is "
            "(re)dispatched",
            session_id,
        )
