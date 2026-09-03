# Spec 012 — Real addresses: autocomplete + pin drop

Build mode. Replaces the six hardcoded locations with anywhere in Bengaluru.

**Precondition:** spec 011 merged and deployed. Android API key restricted to
both package names.

## New concepts introduced here

1. **Session tokens.** Places Autocomplete bills per request, so a 20-keystroke
   search would be 20 billable calls. A session token bundles the typing plus
   the final selection into one billable session. Generate one per search,
   discard it after the user picks. Getting this wrong multiplies your Places
   bill by roughly the length of an address.
2. **Debouncing.** Firing a request on every keystroke is wasteful even with
   session tokens — it floods the network and makes results flicker. Wait ~300ms
   after typing stops, and cancel the pending call if another key arrives.
3. **Reverse geocoding.** Coordinates in, human address out. Needed because a
   dropped pin has no address until you ask for one.
4. **Configuration over code.** The service area lives in environment
   variables, so it can be narrowed to a few kilometres for a real-world test
   from the Render dashboard — no deploy, no rebuild.
5. **Client checks are UX, server checks are rules.** The app pre-checks the
   service area to give an instant message; the server enforces it because a
   patched app can send anything. Same reasoning as the fare.

## Guardrails

- **Do NOT add Distance Matrix or change the fare formula.** Haversine × 1.4
  stays for now. That is spec 013.
- **Do NOT add live location tracking or a map on the driver's job screen.**
  Spec 014.
- **Do NOT create a second API key.** The Android key covers client-side calls.
  A server key is only needed when the backend starts calling Google, which is
  spec 013.
- Verify every Google API request and response shape against current docs, not
  memory. Named below.
- Branch. Tell me before pushing.

## Decisions being implemented

| Decision | Value |
|---|---|
| Service area | 25km radius, centre configurable |
| Centre | Bengaluru, approx 12.9716, 77.5946 — verify |
| Trip distance cap | None |
| Address entry | Autocomplete **and** map pin drop |
| Autocomplete region | India, biased toward the service centre |

---

# PART A — Google Cloud (yours)

Cloud Console → project `volt-2b36f` → APIs & Services → **Enable APIs**:

- **Places API (New)** — autocomplete and place details
- **Maps SDK for Android** — the map widget
- **Geocoding API** — reverse geocoding for pin drops

Then Credentials → the Android key → **API restrictions** → add those three to
the existing allowlist. Leave the Android app restrictions as they are.

Save, wait a few minutes, and re-test phone sign-in on both apps before
continuing — restriction changes are the classic way to break auth silently.

---

# PART B — Backend

## B1. Service area configuration

`app/config.py`, with Bengaluru defaults:

```python
    service_center_lat: float = 12.9716
    service_center_lng: float = 77.5946
    service_radius_km: float = 25.0
```

Add all three to `.env.example` with a comment that they are deliberately
configurable so the area can be narrowed for field testing without a deploy.

Do **not** add them to `.env` unless overriding — defaults should work.

## B2. Validation

**New file: `app/services/service_area.py`**

```python
class OutsideServiceArea(Exception):
    """Raised when a pickup or drop falls outside the serviceable radius."""
```

A `check_within_service_area(lat, lng)` using the existing `road_distance_m`'s
haversine — extract the straight-line part if it is currently fused with the
road factor, because **straight-line is correct here**. Service area is "how
far from the centre," not "how far to drive."

Wire into:

- `POST /api/v1/bookings/estimate` — check both pickup and drop
- `POST /api/v1/bookings` — same

**422** with a message naming which end is outside and by roughly how much:
`"Drop location is outside our service area (32km from centre, limit 25km)."`
A bare "outside service area" leaves the customer guessing whether to move the
pickup or the drop.

## B3. Expose the service area

`GET /api/v1/service-area`, public, returning centre lat/lng and radius in km.

The app needs it to centre the map, bias autocomplete, and pre-check before
submitting. Serving it from the same config keeps one source of truth — narrow
the radius in Render and both apps follow without a rebuild.

## B4. Store the place id

Add a nullable `pickup_place_id` and `drop_place_id` (`String(255)`) to
`bookings`, accepted optionally on `LocationIn`.

Not used yet. Worth capturing now because a Google place id is stable and
re-resolvable, whereas a free-text address is not — and back-filling it later
is impossible.

Migration required.

## B5. Tests

- Inside the radius → accepted
- Pickup outside → 422 naming pickup
- Drop outside → 422 naming drop
- Exactly at the boundary → accepted
- A booking with `place_id` values round-trips them
- `GET /service-area` reflects overridden config values

---

# PART C — Customer app

## C1. Dependencies

```powershell
cd $env:USERPROFILE\projects\volt\customer_app
flutter pub add google_maps_flutter
```

**`google_maps_flutter`** — Google's official map widget. Needed for pin drop.
Replaces nothing.

For Places, **evaluate before adding a wrapper package**: third-party Places
wrappers go stale against the Places API (New), and calling the REST endpoint
with the `dio` you already have may be simpler and more durable. Report which
you chose and why.

Android setup for `google_maps_flutter` needs the API key in
`AndroidManifest.xml` and a `minSdkVersion` bump. **Read the package's current
README from the pub cache** rather than writing the manifest from memory.

Docs to verify against:
- https://developers.google.com/maps/documentation/places/web-service/op-overview
- https://developers.google.com/maps/documentation/geocoding/overview
- https://pub.dev/packages/google_maps_flutter

## C2. Places service

`lib/features/booking/data/places_service.dart` — an interface plus a real
implementation, matching the pattern used everywhere else:

```dart
abstract interface class PlacesService {
  /// Autocomplete suggestions for [query], biased to the service area.
  Future<List<PlaceSuggestion>> suggest(String query, String sessionToken);

  /// Full details, including coordinates, for a chosen suggestion.
  Future<PlaceDetail> detail(String placeId, String sessionToken);

  /// Address for a dropped pin.
  Future<String> reverseGeocode(double lat, double lng);
}
```

Requirements:

- Restrict results to India
- Bias toward the service centre from `GET /service-area`
- **Session token generated per search, passed to both `suggest` and
  `detail`, discarded after selection.** Comment why, since it looks like
  pointless plumbing otherwise
- Errors translate to the existing `ApiException` shape so screens handle them
  uniformly

## C3. Address picker

`lib/features/booking/presentation/address_picker_screen.dart` — one screen
used for both pickup and drop, opened from the booking home screen.

**Search mode** (default):
- Text field, autofocus
- **Debounce 300ms**, minimum 3 characters
- Results list; tapping one fetches details and returns

**Map mode** (a toggle):
- `GoogleMap` centred on the service area, or the user's location if granted
- A fixed centre pin — the map moves under a stationary pin, which is the
  standard pattern and avoids fiddly marker dragging
- Reverse geocode on idle, showing the resolved address at the bottom
- Confirm button returns the coordinates plus that address

**Both modes:**
- Pre-check against the service area before returning. Outside → inline message,
  do not return a location the server will reject
- Location permission is optional. Denied is fine — the map just centres on the
  service centre. Do not block the flow on it

## C4. Booking home

Replace the two dropdowns with tappable rows opening the picker. Show the
chosen address, and a Change action.

**Delete `lib/features/booking/data/bengaluru_locations.dart`** and the
`Location` model if it is now redundant with `PlaceDetail`.

Keep the rest of the flow — goods, weight, vehicle select — unchanged.

## C5. Service area provider

`FutureProvider` fetching `GET /service-area` once, cached for the session.
Used for map centring, autocomplete bias, and the pre-check.

---

## Step D — Verify on device

Against production:

| Test | Expected |
|---|---|
| Type "Koramangala" | Suggestions appear after a pause, not per keystroke |
| Pick one | Address fills, coordinates captured |
| Switch to map mode, drag, confirm | Address resolves from the pin |
| Search an address 40km out (e.g. Hosur) | Blocked in-app with a clear message |
| Full booking with real addresses | Succeeds, real address in the DB |
| Deny location permission | Map still works, centred on Bengaluru |
| Airplane mode, then search | Legible error, no crash |

**Then check billing.** Cloud Console → Billing → Reports, filtered to Places
and Geocoding. After ~10 searches you want a small number of billable sessions,
not one per keystroke. If the count looks like your keystrokes, session tokens
are not working — that is the single most expensive mistake in this spec.

## Step E — Update `CLAUDE.md`

Service area config and that it is deliberately env-driven, session tokens and
why, the client-checks-are-UX split, `place_id` stored but unused, and that the
fare still uses haversine until spec 013.

## Step F — Report and stop

1. Files created, edited, deleted, and the migration revision
2. Which Places approach you chose — wrapper package or direct REST — and why
3. The step D table with real results
4. Billing report numbers after the search test
5. Anything in the Google docs that differed from this spec's assumptions
6. Anything you were tempted to build and did not

Do not add Distance Matrix. Do not push.
