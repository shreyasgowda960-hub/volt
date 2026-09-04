# Spec 014 — Real road distance

Build mode. Fares stop being a guess.

**Precondition:** spec 013 merged. `GOOGLE_MAPS_API_KEY` working in Render and
locally.

## What changes

`road_distance_m()` currently returns haversine × 1.4, and ETA divides by a flat
20 km/h. Both numbers were invented. After this, distance and duration come from
Google.

**Fares will rise**, roughly 10–30% on routes where geography forces a detour —
which is most cross-Bengaluru trips. That is the point: a flat multiplier
undercharges exactly where a driver spends the most fuel and time.

## New concepts introduced here

1. **Distance is cacheable, duration is not.** Road distance between two fixed
   points is stable — cache it. Traffic-aware duration at 6pm differs from 3am,
   so a cached duration is a wrong duration. They have different lifetimes and
   must be treated separately, which is not obvious when one API call returns
   both.
2. **Graceful degradation on a paid dependency.** Fare estimation sits on the
   critical path. If Google is down, quota is exhausted, or the key is
   misconfigured, "nobody can book" is a worse outcome than "fares are
   approximate for an hour." The fallback needs to be deliberate, visible in
   logs, and recorded per booking.
3. **Recording provenance.** A booking priced by fallback is not the same
   artifact as one priced by Google. When you audit fares later, "which of
   these used real distance" must be answerable from the row, not inferred.
4. **Deprecation drift.** Google has been moving Distance Matrix functionality
   into the Routes API. Which endpoint is current matters, and this spec does
   not assume — see the verification note below.

## Guardrails

- **Verify which API is current before writing any client.** Google's Distance
  Matrix API and the newer Routes API (`computeRouteMatrix`) both exist and
  their status has been changing. Check
  https://developers.google.com/maps/documentation/routes and
  https://developers.google.com/maps/documentation/distance-matrix — use
  whichever Google currently recommends for new work, and **report which you
  chose and why**. Do not write request or response shapes from memory.
- **Check the caching terms**, as you did in 012. Google's Service Specific
  Terms constrain what may be stored and for how long. If distance results are
  not cacheable under the same reasoning that ruled out autocomplete text, say
  so and stop — do not build a cache the licence forbids.
- **Do NOT change the service-area check.** That uses straight-line distance
  from a centre point and is correct as it is. Only trip distance changes.
- **Do NOT change fare rates.** Whether ₹8/km is right once distances are real
  is a separate business question.
- **Do NOT touch the Flutter apps.** The API contract does not change.
- Branch. Tell me before pushing.

---

# PART A — Cloud Console (yours)

1. **Enable** whichever API step B1 determines is current — Routes API or
   Distance Matrix API.
2. **Server key** → API restrictions → add it alongside Places API (New) and
   Geocoding API. Do **not** add it to the Android key; this is server-side
   only.
3. **Usage alerts** on the new API's per-day and per-minute quotas, same as you
   set for Places.

The server key is already in Render and `.env`, so no new secret.

---

# PART B — Backend

## B1. Decide the endpoint

Read the current docs, determine which API to use, and report the decision
before writing the client. Include what the request needs (origin, destination,
travel mode, whether traffic-aware duration requires a departure time) and what
the response returns.

## B2. New file: `app/services/routing.py`

An interface plus a Google implementation, matching the pattern used elsewhere:

```python
class RouteResult(NamedTuple):
    distance_m: int
    duration_s: int
    source: DistanceSource   # google | haversine


class RoutingService(Protocol):
    async def route(
        self, origin_lat, origin_lng, dest_lat, dest_lng
    ) -> RouteResult: ...
```

Requirements:

- Uses the existing `GOOGLE_MAPS_API_KEY`
- Travel mode: driving
- Timeout on the outbound call — a hanging Google request must not hang your
  endpoint. A few seconds, then fall back
- Errors, timeouts, quota rejections and malformed responses all route to the
  fallback rather than propagating

## B3. The fallback

When Google fails for any reason:

- Return the existing haversine × 1.4 distance and 20 km/h duration
- `source = haversine`
- **`logger.warning` with the reason**, not `info`. This is a degraded state and
  should be visible when you go looking for why fares dipped

Keep `road_distance_m()` and `eta_minutes()` exactly as they are. They stop
being the primary path and become the fallback, and they remain correct for the
service-area radius check.

## B4. Cache distance, not duration

**Only if step B1's licence check permits it.**

New table `route_distances`:

- `origin_key`, `dest_key` — coordinates rounded to 4 decimals (~11m),
  composite unique
- `distance_m`
- `created_at`

Rounding matters for the same reason as the place cache: raw GPS gives
`12.93521847`, and two taps on one spot produce different values, so an exact
match would never hit.

**Duration is not cached.** It is traffic-dependent, so a stored duration is
stale the moment it is written. That means a cache hit still needs a Google
call for duration — which sounds pointless until you consider that a hit lets
you serve a *fare* immediately and treat duration as best-effort. Decide which
of these you want and say why:

- **(a)** Cache hit serves distance from cache and still calls Google for
  duration. Correct ETAs, no cost saving.
- **(b)** Cache hit serves distance from cache and computes duration from the
  20 km/h fallback. Saves the call, degrades the ETA.
- **(c)** Cache both, with a short TTL on duration (say 15 minutes), accepting
  staleness within that window.

My inclination is **(c)** with a short TTL, because ETA precision matters less
than fare correctness and the cost saving is the point. But this is a real
trade — argue for a different one if you disagree.

Whichever you pick: if the terms impose a retention limit as they did on
geocoded coordinates, implement a real scheduled **delete**, not a
TTL-on-read.

## B5. Record provenance

Add to `bookings`:

- `distance_source` — enum `google` / `haversine`, not null, defaulting to
  `haversine` for existing rows

Migration required. Set at booking creation from the `RouteResult`.

This is what makes "were these fares real?" answerable later. Without it a
degraded hour is invisible in the data forever.

## B6. Wire into the fare service

`estimate_all` and `create_booking` both call `routing.route()` instead of
`road_distance_m()`.

**Important:** `create_booking` recomputes distance server-side rather than
trusting the estimate. Keep that. It now costs an API call, which is the
correct price for not trusting a client-supplied distance — and the cache
should make it a hit, since the customer just estimated the same route.

## B7. Fix the tests that are now wrong by design

`test_distance.py` asserts `19787` for Koramangala → Whitefield. That number was
never a fact about the world, only about the multiplier — and it is about to
stop being what the system returns.

- Keep the haversine tests, retargeted at the fallback and the service-area
  check, which still use it
- Add routing tests with a **mocked** Google client. Never call Google in tests
- Cover: success, timeout, quota rejection, malformed response, and confirm
  each falls back with `source = haversine`
- Cover the cache: miss then hit, and prove the hit issues no outbound call
- **Prove the fallback tests can fail** — make the fallback return the wrong
  source and confirm they go red

## B8. One live check

A single real call against the deployed key for the Koramangala → Whitefield
route, printing distance, duration, and source. Report the numbers next to the
old `19787`.

That is the only thing that proves the field masks and request shape are right;
a mocked test proves your code, not your integration.

---

## Step C — Verify

| Test | Expected |
|---|---|
| Estimate a known route | Distance differs from haversine, `source: google` in logs |
| Same route again | Cache hit, no outbound call in logs |
| Estimate with the key deliberately blanked | Falls back, `logger.warning`, booking still works |
| Create a booking | `distance_source = google` in the row |
| Fares vs before | Higher on detour-heavy routes, roughly unchanged on direct ones |
| Service area rejection | Still works, still straight-line |

The third row is the one that matters most. Break it on purpose — temporarily
set an invalid key locally — and confirm a customer can still book. A fare
service that fails closed on a third-party outage is worse than one that
degrades.

Then on device: book Koramangala → Whitefield and compare the fare to what you
remember. It should be visibly higher.

## Step D — Update `CLAUDE.md`

Which API, the cache and its duration decision, the fallback and that it logs
at warning level, `distance_source` on bookings, and that fares rose — with
rough numbers, so a future you knows prices changed on this date and why.

## Step E — Report and stop

1. Which API you chose and why
2. What the caching terms permit, quoted
3. Which duration option from B4 and your reasoning
4. Files created and edited, migration revision
5. The B8 live numbers next to the old `19787`
6. Step C results
7. Anything you were tempted to build and did not

Do not touch the Flutter apps. Do not push.
