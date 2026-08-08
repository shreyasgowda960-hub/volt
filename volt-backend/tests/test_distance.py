from app.utils.distance import road_distance_m

KORAMANGALA = (12.9352, 77.6245)
WHITEFIELD = (12.9698, 77.7500)


def test_koramangala_to_whitefield():
    assert road_distance_m(*KORAMANGALA, *WHITEFIELD) == 19787


def test_identical_points_is_zero():
    lat, lng = KORAMANGALA
    assert road_distance_m(lat, lng, lat, lng) == 0


def test_symmetric():
    a_to_b = road_distance_m(*KORAMANGALA, *WHITEFIELD)
    b_to_a = road_distance_m(*WHITEFIELD, *KORAMANGALA)
    assert a_to_b == b_to_a
