"""Enrollment session state machine (BE-05, FSD-AI.md §8, FR-ENR-08).

Single source of truth for which `EnrollmentState` transitions are legal.
Deliberately kept independent of HTTP/router concerns and of *how* a
transition is triggered (staff action via an API call here in BE-05, an
async upload-validation/QC/embedding job in BE-06/BE-07, or a revocation
job in BE-08) so every later task reuses this module instead of
re-encoding the diagram.

Diagram (FSD-AI.md §8):
    CREATED -> CONSENTED -> CAPTURING -> CAPTURED -> QC_RUNNING ->
        (REJECTED_QUALITY -> CAPTURING) | QC_PASSED -> EMBEDDING -> ENROLLED
    Terminal alternates: CANCELLED, REVOKED.

Design notes:
- `CANCELLED` is reachable from any non-terminal state (staff can abandon
  an in-progress enrollment at any point before it completes) and is
  itself terminal.
- `REVOKED` is reachable only from `ENROLLED` — revocation (FR-ENR-09,
  BE-08 scope) undoes a *completed* enrollment (deletes gallery
  embeddings/media). Abandoning a session that never reached `ENROLLED`
  is a cancellation, not a revocation.
- `ENROLLED`, `CANCELLED`, `REVOKED` have no outgoing transitions — they
  are the three terminal states of the machine.

This module is agnostic to the *kind* of capture motion (head-orientation
sweep per ASM-03, corrected 2026-08-30) — it only ever deals with
`EnrollmentState` values, never with pose/media semantics.
"""

from app.models.enums import EnrollmentState

TERMINAL_STATES: frozenset[EnrollmentState] = frozenset(
    {EnrollmentState.ENROLLED, EnrollmentState.CANCELLED, EnrollmentState.REVOKED}
)

# Explicit allow-list of legal `current -> {targets}` transitions. Kept as a
# plain dict (not derived/generated) so the table is easy to audit against
# the FSD diagram at a glance.
_TRANSITIONS: dict[EnrollmentState, frozenset[EnrollmentState]] = {
    EnrollmentState.CREATED: frozenset({EnrollmentState.CONSENTED, EnrollmentState.CANCELLED}),
    EnrollmentState.CONSENTED: frozenset({EnrollmentState.CAPTURING, EnrollmentState.CANCELLED}),
    EnrollmentState.CAPTURING: frozenset({EnrollmentState.CAPTURED, EnrollmentState.CANCELLED}),
    EnrollmentState.CAPTURED: frozenset({EnrollmentState.QC_RUNNING, EnrollmentState.CANCELLED}),
    EnrollmentState.QC_RUNNING: frozenset(
        {EnrollmentState.REJECTED_QUALITY, EnrollmentState.QC_PASSED, EnrollmentState.CANCELLED}
    ),
    EnrollmentState.REJECTED_QUALITY: frozenset(
        {EnrollmentState.CAPTURING, EnrollmentState.CANCELLED}
    ),
    EnrollmentState.QC_PASSED: frozenset({EnrollmentState.EMBEDDING, EnrollmentState.CANCELLED}),
    EnrollmentState.EMBEDDING: frozenset({EnrollmentState.ENROLLED, EnrollmentState.CANCELLED}),
    EnrollmentState.ENROLLED: frozenset({EnrollmentState.REVOKED}),
    EnrollmentState.CANCELLED: frozenset(),
    EnrollmentState.REVOKED: frozenset(),
}


class IllegalTransitionError(Exception):
    """Raised when `current -> target` is not a legal state-machine edge."""

    def __init__(self, current: EnrollmentState, target: EnrollmentState) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Illegal enrollment state transition: {current} -> {target}")


def allowed_targets(current: EnrollmentState) -> frozenset[EnrollmentState]:
    """States reachable in one legal transition from `current`."""
    return _TRANSITIONS.get(current, frozenset())


def is_terminal(state: EnrollmentState) -> bool:
    return state in TERMINAL_STATES


def can_transition(current: EnrollmentState, target: EnrollmentState) -> bool:
    return target in allowed_targets(current)


def validate_transition(current: EnrollmentState, target: EnrollmentState) -> None:
    """Raise `IllegalTransitionError` unless `current -> target` is legal.

    Callers (routers/services here, worker jobs in BE-06/07/08) MUST call
    this before persisting a new `state` value on an `EnrollmentSession`.
    """
    if not can_transition(current, target):
        raise IllegalTransitionError(current, target)
