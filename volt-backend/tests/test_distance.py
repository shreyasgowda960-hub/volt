"""Haversine distance — no longer the primary path, still load-bearing twice.

Since spec 014, road_distance_m is not what prices a trip; the Routes API is.
These functions survive because two things still depend on them:

  1. The routing fallback, when Google is unreachable or out of quota. See
     test_routing.py, which asserts these exact numbers come back labelled
     `haversine`.
  2. The service-area radius check, which asks "how far from our centre is
     this" — a straight-line question that must NOT move when road distance
     or ROAD_FACTOR changes. See test_service_area.py.

19787 was never a fact about the world, only about the 1.4 multiplier. It is
kept because both survivors above depend on it being stable, not because it
is a good estimate of the drive.
"""

from app.utils.distance import (
    eta_minutes,
    road_distance_m,
    straight_line_distance_m,
)

KORAMANGALA = (12.9352, 77.6245)
WHITEFIELD = (12.9698, 77.7500)


# --- The fallback -------------------------------------------------------


def test_koramangala_to_whitefield_fallback_is_stable():
    """Pinned so a change to the fallback shows up as a test failure rather
    than as fares quietly moving during a Google outage."""
    assert road_distance_m(*KORAMANGALA, *WHITEFIELD) == 19787


def test_fallback_eta_is_the_flat_speed_assumption():
    """The 20km/h figure the fallback still uses. Wrong in a known direction,
    which is why the source label on every booking matters."""
    assert eta_minutes(19787) == 59


def test_identical_points_is_zero():
    lat, lng = KORAMANGALA
    assert road_distance_m(lat, lng, lat, lng) == 0


def test_symmetric():
    """Haversine is symmetric; real road distance often is not, because of
    one-way streets. Another reason the two are not interchangeable."""
    a_to_b = road_distance_m(*KORAMANGALA, *WHITEFIELD)
    b_to_a = road_distance_m(*WHITEFIELD, *KORAMANGALA)
    assert a_to_b == b_to_a


# --- The service-area half ----------------------------------------------


def test_straight_line_is_the_road_distance_without_the_factor():
    """The service area uses the unmultiplied figure on purpose: it asks how
    far from the centre, not how far to drive. If these two ever stop being
    related by exactly ROAD_FACTOR, the split has been broken."""
    from app.utils.distance import ROAD_FACTOR

    straight = straight_line_distance_m(*KORAMANGALA, *WHITEFIELD)
    assert round(straight * ROAD_FACTOR) == road_distance_m(
        *KORAMANGALA, *WHITEFIELD
    )


def test_straight_line_is_shorter_than_the_road_estimate():
    straight = straight_line_distance_m(*KORAMANGALA, *WHITEFIELD)
    assert straight < road_distance_m(*KORAMANGALA, *WHITEFIELD)
