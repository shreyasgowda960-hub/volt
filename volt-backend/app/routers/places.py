"""Address search, proxied.

All three endpoints are authenticated, unlike POST /bookings/estimate which
is deliberately public. The difference is who pays: price discovery costs us
a haversine, whereas these spend real money per call with Google. An
unauthenticated Places proxy is free autocomplete for anyone who reads the
app's traffic, billed to us.

Each call logs the caller's user id. Nothing in VOLT is rate limited yet, and
a sensible per-user cap cannot be chosen without first knowing whether a real
address search is three requests or fifteen. This is that evidence.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.places import (
    AutocompleteRequest,
    AutocompleteResponse,
    PlaceDetailsRequest,
    PlaceSuggestionResponse,
    ResolvedPlaceResponse,
    ReverseGeocodeRequest,
)
from app.services import google_maps, place_cache
from app.services.google_maps import (
    GoogleMapsError,
    GoogleMapsNoResult,
    GoogleMapsNotConfigured,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/places", tags=["places"])

_UNCONFIGURED = (
    "Address search is not available right now. Please type the address "
    "manually or drop a pin."
)
_UPSTREAM_FAILED = "Could not search addresses right now. Please try again."


def _not_configured(where: str, error: Exception) -> HTTPException:
    # 503, not 500: this is a missing configuration value, not a bug, and it
    # is fixed by setting an environment variable rather than by a deploy.
    # Logged at error level because it needs somebody's attention.
    logger.error("%s unavailable: %s", where, error)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNCONFIGURED
    )


def _upstream_failed(where: str, error: Exception) -> HTTPException:
    # 502: we are fine, our upstream is not. Google's own message can name
    # quota exhaustion or key misconfiguration, which are ours to fix and
    # not a customer's to read, so it goes to the log and not the response.
    logger.warning("%s failed: %s", where, error)
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY, detail=_UPSTREAM_FAILED
    )


@router.post("/autocomplete", response_model=AutocompleteResponse)
async def autocomplete(
    payload: AutocompleteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AutocompleteResponse:
    await place_cache.purge_expired(db)

    logger.info(
        "places.autocomplete user=%s chars=%s", user.id, len(payload.query)
    )
    try:
        suggestions = await google_maps.autocomplete(
            payload.query, payload.session_token
        )
    except GoogleMapsNotConfigured as e:
        raise _not_configured("autocomplete", e)
    except GoogleMapsError as e:
        raise _upstream_failed("autocomplete", e)

    return AutocompleteResponse(
        suggestions=[
            PlaceSuggestionResponse(
                place_id=s.place_id,
                description=s.description,
                main_text=s.main_text,
                secondary_text=s.secondary_text,
            )
            for s in suggestions
        ]
    )


@router.post("/details", response_model=ResolvedPlaceResponse)
async def place_details(
    payload: PlaceDetailsRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ResolvedPlaceResponse:
    """Coordinates (and, when fresh, the address) for a chosen place.

    The cache is consulted ONLY when there is no session token, and that
    condition is the whole design rather than an optimisation detail.

    A session token means this call is closing an autocomplete session. Under
    Google's billing that closure is what bundles all the user's keystroke
    requests into one charge; skip it and every one of them is billed
    separately instead. So serving a live search from cache would save one
    Place Details call and buy several autocomplete charges — worse, not
    better. When a token is present we always go to Google.

    Without a token this is a re-resolve of a place id we already hold, no
    session is open, and a cache hit is a pure saving.
    """
    await place_cache.purge_expired(db)

    is_live_search = bool(payload.session_token)
    logger.info(
        "places.details user=%s live_search=%s", user.id, is_live_search
    )

    if not is_live_search:
        cached = await place_cache.get_coordinates(db, payload.place_id)
        if cached is not None:
            lat, lng = cached
            # address is empty here by necessity — see the schema. The caller
            # holds it already.
            return ResolvedPlaceResponse(
                place_id=payload.place_id,
                address="",
                lat=lat,
                lng=lng,
                from_cache=True,
            )

    try:
        resolved = await google_maps.place_details(
            payload.place_id, payload.session_token
        )
    except GoogleMapsNotConfigured as e:
        raise _not_configured("place details", e)
    except GoogleMapsError as e:
        raise _upstream_failed("place details", e)

    # Stored on every fresh resolve, including live searches. The write side
    # is what makes the cache worth anything later; the read side above stays
    # dormant until something re-resolves a saved place id.
    #
    # Stored under BOTH ids when they differ, which they routinely do. Google
    # answers Place Details with its own canonical id, and for address-type
    # predictions — the long "EkY…" blobs autocomplete returns for a street
    # or building, as opposed to a "ChIJ…" establishment — that is not the id
    # that was asked for. Writing only the resolved id meant writing a key
    # nothing ever looks up, so the cache had a silent 0% hit rate for
    # exactly the searches a logistics customer makes most. Found by calling
    # the real API; a stub that echoes back its argument cannot show this.
    #
    # Both are place ids, so both may be stored indefinitely under the terms.
    await place_cache.store_coordinates(
        db, resolved.place_id, resolved.lat, resolved.lng
    )
    if resolved.place_id != payload.place_id:
        await place_cache.store_coordinates(
            db, payload.place_id, resolved.lat, resolved.lng
        )

    return ResolvedPlaceResponse(
        place_id=resolved.place_id,
        address=resolved.address,
        lat=resolved.lat,
        lng=resolved.lng,
        from_cache=False,
    )


@router.post("/reverse-geocode", response_model=ResolvedPlaceResponse)
async def reverse_geocode(
    payload: ReverseGeocodeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ResolvedPlaceResponse:
    """Address for a dropped pin.

    Not cached in either direction. The payload of a reverse geocode IS the
    address, and the terms do not permit caching that — the 30-day exemption
    covers coordinates returned by Geocoding, not the addresses. The
    coordinates it returns are Google's snapped point for the matched
    address, so they are stored: they are legitimately cacheable and they
    belong with the place id.
    """
    await place_cache.purge_expired(db)

    logger.info("places.reverse_geocode user=%s", user.id)
    try:
        resolved = await google_maps.reverse_geocode(payload.lat, payload.lng)
    except GoogleMapsNotConfigured as e:
        raise _not_configured("reverse geocode", e)
    except GoogleMapsNoResult:
        # 404 rather than 502: Google worked, there is simply no address at
        # that point. A pin in a lake is the customer's to move.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No address found at that point. Try moving the pin.",
        )
    except GoogleMapsError as e:
        raise _upstream_failed("reverse geocode", e)

    if resolved.place_id:
        await place_cache.store_coordinates(
            db, resolved.place_id, resolved.lat, resolved.lng
        )

    return ResolvedPlaceResponse(
        place_id=resolved.place_id,
        address=resolved.address,
        lat=resolved.lat,
        lng=resolved.lng,
        from_cache=False,
    )
