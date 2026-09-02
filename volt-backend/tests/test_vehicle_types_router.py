import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app.database import SessionLocal
from app.main import app
from app.models.vehicle_type import VehicleType


@pytest.mark.asyncio
async def test_returns_seeded_rows_in_sort_order():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/vehicle-types")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3

    # sort_order isn't in the response schema (by design — it's an internal
    # ordering hint, not price-list data), so assert order the only way a
    # consumer can observe it: against the known seeded sequence.
    codes = [v["code"] for v in data]
    assert codes == ["bike", "three_wheeler", "mini_truck"]

    for v in data:
        assert set(v.keys()) == {
            "code",
            "label",
            "capacity_kg",
            "base_fare_paise",
            "included_km",
            "per_km_paise",
            "min_fare_paise",
        }


@pytest.mark.asyncio
async def test_inactive_vehicle_type_is_excluded():
    async with SessionLocal() as db:
        await db.execute(
            update(VehicleType).where(VehicleType.code == "mini_truck").values(is_active=False)
        )
        await db.commit()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/vehicle-types")

        assert resp.status_code == 200
        codes = [v["code"] for v in resp.json()]
        assert "mini_truck" not in codes
        assert len(codes) == 2
    finally:
        # This flips shared seed data every other test's fare math depends
        # on — must be restored even if an assertion above fails.
        async with SessionLocal() as db:
            await db.execute(
                update(VehicleType).where(VehicleType.code == "mini_truck").values(is_active=True)
            )
            await db.commit()
