from pydantic import BaseModel, ConfigDict


class VehicleTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    capacity_kg: int
    base_fare_paise: int
    included_km: float
    per_km_paise: int
    min_fare_paise: int
