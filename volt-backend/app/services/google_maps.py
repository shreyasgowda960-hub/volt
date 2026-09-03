"""Thin client for the two Google Maps Platform APIs VOLT calls.

Why this lives on the server at all: an API key with an Android application
restriction does NOT work against the Places or Geocoding *web services* —
Google's security guidance is explicit that an Android-restricted key "cannot
be used with iOS, web services, or JavaScript APIs", and recommends a proxy
between mobile clients and web service endpoints. Calling Google directly
from the app would therefore need a key with no application restriction,
sitting extractable inside every APK, billable to us by anyone who pulls it
out. So the key stays here and the apps call our endpoints.

Every request and response shape below was taken from the current docs, not
from memory:
  Autocomplete   https://developers.google.com/maps/documentation/places/web-service/place-autocomplete
  Place Details  https://developers.google.com/maps/documentation/places/web-service/place-details
  Reverse geocode https://developers.google.com/maps/documentation/geocoding/requests-reverse-geocoding
"""

import logging
from dataclasses import dataclass

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
_PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# No spaces allowed anywhere in a field mask, and autocomplete's paths are
# rooted at `suggestions`. Asking for only what we use keeps the response
# small and, on some SKUs, the request cheaper.
_AUTOCOMPLETE_FIELD_MASK = (
    "suggestions.placePrediction.placeId,"
    "suggestions.placePrediction.text.text,"
    "suggestions.placePrediction.structuredFormat.mainText.text,"
    "suggestions.placePrediction.structuredFormat.secondaryText.text"
)
_DETAILS_FIELD_MASK = "id,formattedAddress,location"

# locationBias.circle.radius is in METRES and Google rejects anything above
# this. Clamped rather than trusted, because service_radius_km is an
# environment variable and a mis-set 100 would otherwise turn every search
# into a 400 that looks like a code bug.
_MAX_BIAS_RADIUS_M = 50_000.0

# India only. `includedRegionCodes` is the Places API (New) field; the legacy
# API's `components=country:in` does not exist here.
_REGION_CODES = ["in"]

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class GoogleMapsNotConfigured(Exception):
    """No GOOGLE_MAPS_API_KEY set.

    Raised at call time rather than at import, so the service still starts
    and everything that does not need Google keeps working. Surfaces as a
    503 naming the missing variable — a server that boots and then fails
    cryptically on first use is worse than one that says what is wrong.
    """


class GoogleMapsError(Exception):
    """Google refused or failed the request.

    Carries a terse technical message for the log; callers map it to a
    generic user-facing message, because Google's own error text can name
    quota states and key problems that are ours to fix, not the customer's
    to read.
    """


class GoogleMapsNoResult(Exception):
    """Google succeeded but had no address for that point.

    Distinct from GoogleMapsError on purpose: a pin in the middle of a lake
    is a real answer the customer needs to act on, not a fault to apologise
    for. Different HTTP status, different message.
    """

    def __init__(self, lat: float, lng: float):
        self.lat = lat
        self.lng = lng
        super().__init__(f"no address for {lat},{lng}")


@dataclass(frozen=True)
class PlaceSuggestion:
    place_id: str
    description: str
    main_text: str
    secondary_text: str


@dataclass(frozen=True)
class ResolvedPlace:
    place_id: str
    address: str
    lat: float
    lng: float


def _api_key() -> str:
    key = get_settings().google_maps_api_key
    if not key:
        raise GoogleMapsNotConfigured(
            "GOOGLE_MAPS_API_KEY is not set; address search is unavailable"
        )
    return key


def _bias_radius_m() -> float:
    settings = get_settings()
    return min(settings.service_radius_km * 1000, _MAX_BIAS_RADIUS_M)


async def autocomplete(query: str, session_token: str) -> list[PlaceSuggestion]:
    """Address suggestions for a partial query.

    Biased to the service area rather than restricted to it. `locationBias`
    and `locationRestriction` are mutually exclusive, and bias is the right
    one: a restriction would silently return nothing for an address just
    outside the radius, where biasing lets the suggestion appear and the
    service-area check explain why it cannot be booked. "Nothing found" and
    "we don't go there" are very different messages to a customer.
    """
    settings = get_settings()
    body = {
        "input": query,
        # Bundles this request with the rest of the user's typing and the
        # final Place Details call into ONE billable session. Omit it, or
        # reuse a token across sessions, and every keystroke-batch becomes
        # its own charge — roughly the length of an address as a multiplier
        # on the Places bill.
        "sessionToken": session_token,
        "locationBias": {
            "circle": {
                "center": {
                    "latitude": settings.service_center_lat,
                    "longitude": settings.service_center_lng,
                },
                "radius": _bias_radius_m(),
            }
        },
        "includedRegionCodes": _REGION_CODES,
        "languageCode": "en",
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            response = await client.post(
                _AUTOCOMPLETE_URL,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": _api_key(),
                    "X-Goog-FieldMask": _AUTOCOMPLETE_FIELD_MASK,
                },
            )
        except httpx.HTTPError as e:
            raise GoogleMapsError(f"autocomplete transport failure: {e}") from e

    if response.status_code != 200:
        raise GoogleMapsError(
            f"autocomplete returned {response.status_code}: {response.text[:300]}"
        )

    payload = response.json()
    suggestions: list[PlaceSuggestion] = []
    # `suggestions` is absent, not empty, when nothing matches.
    for entry in payload.get("suggestions", []):
        # Entries can also be queryPrediction (a search phrase rather than a
        # place). Those have no placeId and cannot be booked, so skip them.
        prediction = entry.get("placePrediction")
        if not prediction:
            continue
        place_id = prediction.get("placeId")
        if not place_id:
            continue
        structured = prediction.get("structuredFormat") or {}
        suggestions.append(
            PlaceSuggestion(
                place_id=place_id,
                description=(prediction.get("text") or {}).get("text", ""),
                main_text=(structured.get("mainText") or {}).get("text", ""),
                secondary_text=(structured.get("secondaryText") or {}).get(
                    "text", ""
                ),
            )
        )
    return suggestions


async def place_details(place_id: str, session_token: str | None) -> ResolvedPlace:
    """Full address and coordinates for a chosen suggestion.

    Passing the session token here is what CLOSES the billing session opened
    by autocomplete. Note it goes in the query string, not the body — the
    autocomplete call takes `sessionToken` as a JSON field, this one takes it
    as `?sessionToken=`. Same value, two different transports.
    """
    params = {}
    if session_token:
        params["sessionToken"] = session_token

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            response = await client.get(
                _PLACE_DETAILS_URL.format(place_id=place_id),
                params=params,
                headers={
                    "X-Goog-Api-Key": _api_key(),
                    "X-Goog-FieldMask": _DETAILS_FIELD_MASK,
                },
            )
        except httpx.HTTPError as e:
            raise GoogleMapsError(f"place details transport failure: {e}") from e

    if response.status_code != 200:
        raise GoogleMapsError(
            f"place details returned {response.status_code}: {response.text[:300]}"
        )

    payload = response.json()
    location = payload.get("location") or {}
    lat, lng = location.get("latitude"), location.get("longitude")
    if lat is None or lng is None:
        raise GoogleMapsError(f"place details for {place_id} carried no location")

    return ResolvedPlace(
        place_id=payload.get("id") or place_id,
        address=payload.get("formattedAddress", ""),
        lat=float(lat),
        lng=float(lng),
    )


async def reverse_geocode(lat: float, lng: float) -> ResolvedPlace:
    """Human address for a dropped pin.

    The Geocoding API is the older style: it answers HTTP 200 and puts the
    real outcome in a `status` field. A client that only checks the HTTP code
    treats REQUEST_DENIED — the response to a misconfigured key — as success
    and hands back an empty address, so `status` is checked explicitly here.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            response = await client.get(
                _GEOCODE_URL,
                params={
                    "latlng": f"{lat},{lng}",
                    "key": _api_key(),
                    "language": "en",
                    "region": "in",
                },
            )
        except httpx.HTTPError as e:
            raise GoogleMapsError(f"reverse geocode transport failure: {e}") from e

    if response.status_code != 200:
        raise GoogleMapsError(
            f"reverse geocode returned HTTP {response.status_code}"
        )

    payload = response.json()
    status = payload.get("status")

    if status == "ZERO_RESULTS" or not payload.get("results"):
        # A real answer, not a failure: mid-lake, unmapped land. The caller
        # turns this into "we could not find an address here", which is
        # different from "something broke".
        raise GoogleMapsNoResult(lat, lng)

    if status != "OK":
        raise GoogleMapsError(
            f"reverse geocode status {status}: "
            f"{payload.get('error_message', 'no error_message')}"
        )

    first = payload["results"][0]
    geometry_location = (first.get("geometry") or {}).get("location") or {}
    return ResolvedPlace(
        place_id=first.get("place_id", ""),
        address=first.get("formatted_address", ""),
        # Google's snapped coordinate for the matched address, which differs
        # slightly from where the pin was dropped. Returning Google's keeps
        # the address and the coordinates describing the same point.
        lat=float(geometry_location.get("lat", lat)),
        lng=float(geometry_location.get("lng", lng)),
    )

