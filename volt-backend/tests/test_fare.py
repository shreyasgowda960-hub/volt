from app.models.vehicle_type import VehicleType
from app.services.fare import _fare_paise


def _make_vehicle(
    code: str,
    base_fare_paise: int,
    included_km: float,
    per_km_paise: int,
    min_fare_paise: int,
) -> VehicleType:
    return VehicleType(
        code=code,
        label=code,
        base_fare_paise=base_fare_paise,
        included_km=included_km,
        per_km_paise=per_km_paise,
        min_fare_paise=min_fare_paise,
        capacity_kg=1,
        sort_order=0,
    )


BIKE = _make_vehicle("bike", 3000, 2.0, 800, 4000)
THREE_WHEELER = _make_vehicle("three_wheeler", 6000, 3.0, 1300, 8000)
MINI_TRUCK = _make_vehicle("mini_truck", 12000, 3.0, 2000, 15000)


def test_bike_under_included_km_floors_to_min():
    assert _fare_paise(BIKE, 1500) == 4000


def test_bike_exactly_at_included_km_boundary_floors_to_min():
    assert _fare_paise(BIKE, 2000) == 4000


def test_bike_5km():
    assert _fare_paise(BIKE, 5000) == 5400


def test_bike_19_787km_matches_verified_endpoint_result():
    assert _fare_paise(BIKE, 19787) == 17229


def test_three_wheeler_3km_floors_to_min():
    assert _fare_paise(THREE_WHEELER, 3000) == 8000


def test_mini_truck_10km():
    assert _fare_paise(MINI_TRUCK, 10000) == 26000


def test_zero_distance_returns_min_fare_not_zero():
    result = _fare_paise(BIKE, 0)
    assert result == 4000
    assert result != 0
