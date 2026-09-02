import pytest

from app.models.booking import BookingStatus
from app.services.booking_lifecycle import _LEGAL_TRANSITIONS, can_transition

_ALL_PAIRS = [
    (frm, to)
    for frm in BookingStatus
    for to in BookingStatus
    if frm != to
]


@pytest.mark.parametrize("frm,to", _ALL_PAIRS)
def test_transition_matches_the_table_exactly(frm, to):
    expected = to in _LEGAL_TRANSITIONS[frm]
    assert can_transition(frm, to) is expected


def test_terminal_states_allow_nothing():
    for terminal in (
        BookingStatus.delivered,
        BookingStatus.cancelled,
        BookingStatus.expired,
    ):
        assert _LEGAL_TRANSITIONS[terminal] == set()


def test_picked_up_cannot_be_cancelled():
    """The one edge worth naming explicitly: goods already with the driver
    means cancellation is a support problem, not self-service."""
    assert not can_transition(BookingStatus.picked_up, BookingStatus.cancelled)


def test_same_status_is_not_a_legal_transition():
    for status in BookingStatus:
        assert not can_transition(status, status)
