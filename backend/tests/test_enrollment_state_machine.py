"""Unit tests for app/services/enrollment_state_machine.py (BE-05, FR-ENR-08).

Exhaustively checks every state pair: legal edges (per FSD-AI.md §8) are
accepted, everything else — including any transition out of a terminal
state — is rejected.
"""

import itertools

import pytest

from app.models.enums import EnrollmentState
from app.services import enrollment_state_machine as fsm

ALL_STATES = list(EnrollmentState)

LEGAL_EDGES = {
    (EnrollmentState.CREATED, EnrollmentState.CONSENTED),
    (EnrollmentState.CREATED, EnrollmentState.CANCELLED),
    (EnrollmentState.CONSENTED, EnrollmentState.CAPTURING),
    (EnrollmentState.CONSENTED, EnrollmentState.CANCELLED),
    (EnrollmentState.CAPTURING, EnrollmentState.CAPTURED),
    (EnrollmentState.CAPTURING, EnrollmentState.CANCELLED),
    (EnrollmentState.CAPTURED, EnrollmentState.QC_RUNNING),
    (EnrollmentState.CAPTURED, EnrollmentState.CANCELLED),
    (EnrollmentState.QC_RUNNING, EnrollmentState.REJECTED_QUALITY),
    (EnrollmentState.QC_RUNNING, EnrollmentState.QC_PASSED),
    (EnrollmentState.QC_RUNNING, EnrollmentState.CANCELLED),
    (EnrollmentState.REJECTED_QUALITY, EnrollmentState.CAPTURING),
    (EnrollmentState.REJECTED_QUALITY, EnrollmentState.CANCELLED),
    (EnrollmentState.QC_PASSED, EnrollmentState.EMBEDDING),
    (EnrollmentState.QC_PASSED, EnrollmentState.CANCELLED),
    (EnrollmentState.EMBEDDING, EnrollmentState.ENROLLED),
    (EnrollmentState.EMBEDDING, EnrollmentState.CANCELLED),
    (EnrollmentState.ENROLLED, EnrollmentState.REVOKED),
}


@pytest.mark.parametrize("current,target", sorted(LEGAL_EDGES, key=lambda e: (e[0], e[1])))
def test_legal_transitions_are_accepted(
    current: EnrollmentState, target: EnrollmentState
) -> None:
    fsm.validate_transition(current, target)  # must not raise
    assert fsm.can_transition(current, target) is True


@pytest.mark.parametrize(
    "current,target",
    [
        pair
        for pair in itertools.product(ALL_STATES, ALL_STATES)
        if pair not in LEGAL_EDGES and pair[0] != pair[1]
    ],
)
def test_illegal_transitions_are_rejected(
    current: EnrollmentState, target: EnrollmentState
) -> None:
    assert fsm.can_transition(current, target) is False
    with pytest.raises(fsm.IllegalTransitionError) as exc_info:
        fsm.validate_transition(current, target)
    assert exc_info.value.current == current
    assert exc_info.value.target == target


@pytest.mark.parametrize("state", ALL_STATES)
def test_self_transitions_are_always_illegal(state: EnrollmentState) -> None:
    assert fsm.can_transition(state, state) is False


@pytest.mark.parametrize(
    "state",
    [EnrollmentState.ENROLLED, EnrollmentState.CANCELLED, EnrollmentState.REVOKED],
)
def test_terminal_states_have_no_outgoing_edges_except_documented(
    state: EnrollmentState,
) -> None:
    assert fsm.is_terminal(state) is True


def test_cancelled_and_revoked_have_zero_outgoing_transitions() -> None:
    assert fsm.allowed_targets(EnrollmentState.CANCELLED) == frozenset()
    assert fsm.allowed_targets(EnrollmentState.REVOKED) == frozenset()


def test_non_terminal_states_are_not_terminal() -> None:
    non_terminal = {
        EnrollmentState.CREATED,
        EnrollmentState.CONSENTED,
        EnrollmentState.CAPTURING,
        EnrollmentState.CAPTURED,
        EnrollmentState.QC_RUNNING,
        EnrollmentState.REJECTED_QUALITY,
        EnrollmentState.QC_PASSED,
        EnrollmentState.EMBEDDING,
    }
    for state in non_terminal:
        assert fsm.is_terminal(state) is False


def test_cancel_is_reachable_from_every_non_terminal_state() -> None:
    for state in ALL_STATES:
        if fsm.is_terminal(state):
            continue
        assert fsm.can_transition(state, EnrollmentState.CANCELLED) is True
