"""Whether a location is somewhere VOLT will actually go.

The app pre-checks this too, so the customer gets an instant message instead
of a round trip. That check is UX; this one is the rule. A patched or
out-of-date client can send any coordinate it likes, and the fare, the
booking and the driver's wasted trip all follow from it being wrong.
"""

from app.config import get_settings
from app.utils.distance import straight_line_distance_m


class OutsideServiceArea(Exception):
    """A pickup or drop falls outside the serviceable radius.

    Carries the same two messages as IllegalTransition: str(e) is terse for
    the log, user_message is the only one that may leave the server.
    """

    def __init__(self, end: str, distance_km: float, radius_km: float):
        self.end = end
        self.distance_km = distance_km
        self.radius_km = radius_km
        super().__init__(
            f"{end} is {distance_km:.1f}km from centre, limit {radius_km:.1f}km"
        )

    @property
    def user_message(self) -> str:
        """Names which end is out and by roughly how much.

        A bare "outside our service area" leaves the customer guessing which
        of the two addresses to change, which is the difference between a
        five-second fix and abandoning the booking.
        """
        return (
            f"{self.end.capitalize()} location is outside our service area "
            f"({self.distance_km:.0f}km from centre, limit "
            f"{self.radius_km:.0f}km)."
        )


def distance_from_centre_km(lat: float, lng: float) -> float:
    settings = get_settings()
    metres = straight_line_distance_m(
        settings.service_center_lat, settings.service_center_lng, lat, lng
    )
    return metres / 1000


def check_within_service_area(lat: float, lng: float, end: str) -> None:
    """Raises OutsideServiceArea if (lat, lng) is beyond the radius.

    Straight-line distance, not road distance, and that is deliberate. The
    service area answers "how far from our centre is this", not "how far
    would we drive to it". Using the road estimate would make the boundary
    depend on the winding factor, so raising ROAD_FACTOR later would quietly
    shrink the serviceable map — and with a real routing API it would mean
    the same address could be inside the area one day and outside it the
    next, depending on traffic.

    `end` is "pickup" or "drop" and exists only to name the offending end in
    the message.
    """
    settings = get_settings()
    distance_km = distance_from_centre_km(lat, lng)
    # Strictly greater: a location exactly on the boundary is inside. The
    # boundary has to belong to one side or the other, and refusing a booking
    # for being precisely 25.000km out is indefensible to a customer.
    if distance_km > settings.service_radius_km:
        raise OutsideServiceArea(end, distance_km, settings.service_radius_km)
