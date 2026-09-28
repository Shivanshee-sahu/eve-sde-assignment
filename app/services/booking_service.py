from app.models import Booking


class InvalidBookingTransition(Exception):
    """Raised when a booking is asked to enter an unsupported state."""


ALLOWED_TRANSITIONS = {
    "PENDING": {"CONFIRMED", "FAILED", "CANCELLED"},
    "CONFIRMED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
}


def transition_booking(booking: Booking, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(booking.status, set()):
        raise InvalidBookingTransition(f"Cannot transition booking from {booking.status} to {target}")
    booking.status = target
