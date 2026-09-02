from app.models.booking import BookingStatus

# A booking can only move along these edges. Illegal transitions are
# rejected explicitly rather than silently allowed. `picked_up` cannot be
# cancelled — the goods are already with the driver, so that's a support
# problem, not a self-service action. `delivered`, `cancelled`, `expired`
# are terminal.
_LEGAL_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.pending: {
        BookingStatus.driver_assigned,
        BookingStatus.cancelled,
        BookingStatus.expired,
    },
    BookingStatus.driver_assigned: {
        BookingStatus.picked_up,
        BookingStatus.cancelled,
    },
    BookingStatus.picked_up: {BookingStatus.delivered},
    BookingStatus.delivered: set(),
    BookingStatus.cancelled: set(),
    BookingStatus.expired: set(),
}

# Which timestamp column a status change must write. Enforced by every
# transition function below — the schema derives status from these, and
# that invariant only holds if nothing sets status without its timestamp.
_TIMESTAMP_COLUMN: dict[BookingStatus, str] = {
    BookingStatus.driver_assigned: "driver_assigned_at",
    BookingStatus.picked_up: "picked_up_at",
    BookingStatus.delivered: "delivered_at",
    BookingStatus.cancelled: "cancelled_at",
    BookingStatus.expired: "expired_at",
}


# Derived, not hand-listed: a terminal status is exactly one with nowhere
# left to go. Adding a status to _LEGAL_TRANSITIONS keeps this correct for
# free, where a second hardcoded list would quietly drift out of step.
TERMINAL_STATUSES: frozenset[BookingStatus] = frozenset(
    status for status, next_statuses in _LEGAL_TRANSITIONS.items() if not next_statuses
)


def can_transition(from_status: BookingStatus, to_status: BookingStatus) -> bool:
    return to_status in _LEGAL_TRANSITIONS.get(from_status, set())


# What a caller is actually told when a transition is refused.
#
# Keyed on the booking's CURRENT status, not on the illegal move, because the
# current state is the part that is useful: "already picked up" tells a driver
# what happened, where "cannot move from X to Y" only describes our state
# machine. It also happened to describe it in Python: f"{BookingStatus.picked_up}"
# renders as "BookingStatus.picked_up", and that string was reaching drivers.
_STATE_MESSAGE: dict[BookingStatus, str] = {
    BookingStatus.pending: "No driver has accepted this booking yet",
    BookingStatus.driver_assigned: "This booking has not been picked up yet",
    BookingStatus.picked_up: "This booking has already been picked up",
    BookingStatus.delivered: "This booking has already been delivered",
    BookingStatus.cancelled: "This booking was cancelled",
    BookingStatus.expired: "This booking expired before a driver accepted it",
}


class IllegalTransition(Exception):
    """Refused state change.

    Carries two messages on purpose. str(e) is for the log and names the
    statuses; user_message is the only one that may leave the server.
    """

    def __init__(self, from_status: BookingStatus, to_status: BookingStatus):
        self.from_status = from_status
        self.to_status = to_status
        # .value rather than the enum member, so that even a careless
        # detail=str(e) somewhere in the future cannot leak
        # "BookingStatus.picked_up" into an HTTP response.
        super().__init__(
            f"illegal transition {from_status.value} -> {to_status.value}"
        )

    @property
    def user_message(self) -> str:
        """Safe to return over HTTP. No status codes, no enum reprs."""
        return _STATE_MESSAGE.get(
            self.from_status, "This booking can no longer be updated"
        )


class BookingAlreadyClaimed(Exception):
    """Raised when claim_booking's atomic UPDATE matches zero rows because
    another driver won the race. Also raised (with a different detail message
    picked by the caller) when the booking simply isn't pending any more for
    a reason other than expiry — see claim_booking's docstring."""

    def __init__(self, public_code: str):
        self.public_code = public_code
        super().__init__(f"Booking {public_code} is no longer available")


class BookingExpired(Exception):
    """Distinct from BookingAlreadyClaimed: the claim failed because the
    booking expired, not because another driver took it. Telling a driver
    'someone else took it' when nobody did is actively misleading."""

    def __init__(self, public_code: str):
        self.public_code = public_code
        super().__init__(f"Booking {public_code} expired before it was accepted")


class BookingNotFound(Exception):
    def __init__(self, public_code: str):
        self.public_code = public_code
        super().__init__(f"No booking {public_code}")


class VehicleTypeMismatch(Exception):
    def __init__(self, driver_vehicle_type: str, booking_vehicle_type: str):
        self.driver_vehicle_type = driver_vehicle_type
        self.booking_vehicle_type = booking_vehicle_type
        super().__init__(
            f"Driver's vehicle type {driver_vehicle_type!r} does not match "
            f"booking's {booking_vehicle_type!r}"
        )


class DriverOffline(Exception):
    pass


class DriverHasActiveBooking(Exception):
    """Raised when a driver already holds a booking in driver_assigned or
    picked_up. Used by claim_booking to block accepting a second job before
    finishing the first — see the one_active_booking_per_driver partial
    unique index, which is the actual enforcement; this is the friendly
    message for the common (non-racing) case."""

    def __init__(self, public_code: str):
        self.public_code = public_code
        super().__init__(
            f"Already assigned to booking {public_code} — finish it before "
            "accepting another"
        )


def timestamp_column_for(status: BookingStatus) -> str:
    return _TIMESTAMP_COLUMN[status]
