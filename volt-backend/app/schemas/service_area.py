from pydantic import BaseModel


class ServiceAreaResponse(BaseModel):
    """Where VOLT operates, as the apps need to know it.

    One source of truth for three separate client concerns: where to centre
    the map, where to bias address autocomplete, and what to pre-check before
    submitting. Narrowing the radius in Render moves all three at once, with
    no rebuild of either app.
    """

    center_lat: float
    center_lng: float
    radius_km: float
