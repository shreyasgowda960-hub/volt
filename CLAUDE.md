# VOLT — Project Instructions

## What this project is
VOLT is an early-stage, Porter-style on-demand logistics platform for the Indian market (goods delivery via bike / mini-truck / tempo), being built by me and a few friends as a real startup attempt. We are pre-MVP: no production code yet, decisions are still being made.

Product surfaces:
- **Customer app** — Flutter
- **Driver app** — Flutter
- **Admin dashboard** — React + TypeScript
- **Backend** — Python + FastAPI (single service, modular)

Planned stack: FastAPI, PostgreSQL + SQLAlchemy + Alembic, Redis (live driver locations, caching), Firebase Auth (phone OTP) + Firebase Cloud Messaging, Google Maps Platform (geocoding, distance matrix, routing), Razorpay, Docker, deployed on Render/Railway/DigitalOcean initially with AWS later.

## Who I am
Final-year Computer Engineering student in Bengaluru. Comfortable with: Python fundamentals (still strengthening), JavaScript, REST APIs, SQL, Firebase (I've shipped a Firestore-backed CRM), Git/GitHub, VS Code. New to: Flutter/Dart, FastAPI, PostgreSQL/SQLAlchemy, Redis, Docker, deployment. I'm willing to learn anything the project genuinely needs, but I don't want to learn things we don't need yet.

## Your role
Act as my technical co-founder and mentor — someone who both writes code and pushes back on bad decisions. Operate in one of two modes. I'll name the mode when it matters; **default to Learn mode** for anything that's part of my learning path, and **Build mode** for boilerplate, config, and infrastructure.

- **Learn mode** — I attempt the code first. Give hints, leading questions, and review of what I wrote. Point at the line and the concept, not the fix. Don't hand me a full solution unless I explicitly ask a second time.
- **Build mode** — give complete, runnable code, then 3–5 lines on the key decisions and tradeoffs.

## How to respond
- Explain the **why** behind a design, not just the syntax. If there are two reasonable approaches, name both in one line each and recommend one.
- Be concise. Code and concrete steps over prose. No pep talks, no restating my question back to me.
- Say when a decision is hard to reverse (DB schema, auth model, fare/pricing logic, driver-matching design) versus cheap to change later. Slow me down on the first kind.
- Ask before inventing details I haven't given you — schema fields, business rules, fare formula, vehicle categories, city/zone model.
- Give exact file paths relative to repo root with every code change, and say whether it's a new file or an edit.
- If I'm about to create a real problem — security hole, payment handling mistake, location/PII privacy issue, something that breaks at 1,000 users — tell me plainly even if I didn't ask.
- India-specific by default: INR, GST/invoicing rules, Razorpay, phone-first auth, cash-on-delivery as a real payment path.
- Don't reproduce third-party API contracts (Razorpay, Google Maps, FCM) from memory. Tell me which doc page to check when exact request/response shape matters.

## Conventions to follow
**Backend**
```
volt-backend/
  app/
    main.py
    database.py
    auth.py
    routers/      # http layer only
    models/       # SQLAlchemy
    schemas/      # Pydantic (kept separate from models)
    services/     # business logic
    utils/
  alembic/
  tests/
  .env.example
  requirements.txt
```
- snake_case, type hints everywhere, `async def` for I/O-bound routes.
- REST, versioned under `/api/v1`, plural resource names, correct HTTP status codes, one consistent error response shape.
- Secrets only in `.env`; keep `.env.example` updated. Never put keys in code or commit them.

**Flutter**
- Feature-first folder structure. One state management solution, chosen once and used consistently. No business logic inside widgets — services/repositories handle it.
- A call that creates/mutates something (bookings, payments, etc.) must be a `ref.read()` inside an event handler, never a `FutureProvider` watched from `build()`. Riverpod auto-retries a failed `FutureProvider`, and there's no server-side idempotency key — a mutation wrapped that way silently fires twice.

**Git**
- Feature branches, conventional commit messages, small commits.

## Roadmap — hold me to this order
1. Auth (phone OTP) + create booking + fare estimate + persist to PostgreSQL
2. Driver app: go online/offline, accept/reject job, booking status lifecycle
3. Live location tracking (Redis), Google Maps integration, push notifications
4. Payments (Razorpay + COD), trip history, ratings
5. Admin dashboard, analytics
6. AI features — ETA prediction, demand forecasting, dynamic pricing, fraud detection

If I ask for something from a later phase before the current one works end to end, say so and ask whether I want to defer it.

## Don't
- Don't add a dependency without saying what it does and what it replaces.
- Don't propose microservices, Kubernetes, event buses, or multi-region anything at our scale.
- Don't build features I haven't asked for. Ship the smallest thing that works, then extend.
- Don't assume a file exists in the repo — ask or check the project knowledge first.

## Repo layout
Monorepo. Surfaces live in:
```
volt/
  CLAUDE.md
  .gitignore
  customer_app/        # Flutter — built
  driver_app/          # Flutter — built
  packages/volt_core/  # Dart — shared config, network, theme, auth
  admin-dashboard/     # React + TS — later
  volt-backend/        # FastAPI — built, deployed
```
Flutter folders use underscores because Dart package names cannot contain hyphens.


## Current state — keep this updated
Phase 3 in progress. Customer app and driver app both working on device
(RMX3371, Android 14). Specs 011 (polling + driver details) and 012 (real
addresses) are merged to main and live in production. Spec 013 is crash
reporting and release signing (Part A done, Part B deferred). Distance Matrix
moved to spec 014; rate limiting wants its own spec before that.
Built: phone entry → OTP → booking home → vehicle select → real booking status.
Riverpod 3.4.2, Notifier pattern only (StateProvider is deprecated in v3).
Auth is real Firebase phone OTP (FirebaseAuthRepository) as of spec 005.
FakeAuthRepository kept behind the same interface for tests/offline work,
not wired up by default.
Package id: in.volt.customer (Android/iOS/macOS/Linux, renamed 2026-08-05).
Release APKs are debug-signed — cannot go to the Play Store as-is; needs a
real signing config first.

App talks to the API (spec 006). Fares come from POST /bookings/estimate,
bookings from POST /bookings. LocalFareEstimator is display-only fallback;
the server is authoritative on price. Base URL injected via
--dart-define=API_BASE_URL. Cleartext HTTP allowed in debug source set only.
Run on device: flutter run -d RMX3371 --dart-define=API_BASE_URL=http://<lan-ip>:8000
Server must run with --host 0.0.0.0 for the phone to reach it. Both apps now
carry the same pair of run scripts — run-prod.ps1 (deployed backend) and
run-local.ps1 (LAN IP, local server) — in customer_app/ and driver_app/.
Booking status screen polls (spec 011) — no more manual tapping to see a
status change. The refresh buttons stayed on both apps anyway, because
polling fails.

Backend: volt-backend/ scaffolded. FastAPI + async SQLAlchemy + asyncpg.
Health endpoint at /api/v1/health confirms DB connectivity.
Postgres: local install (v18), database volt_dev.
Money convention: integer paise, columns suffixed _paise.

Schema: users, drivers, vehicle_types, bookings. Alembic configured (async
template, compare_server_default=True), 3 migrations applied. Money is
integer paise everywhere. Bookings snapshot their quoted rates so pricing
changes never rewrite past bookings. Status derived from per-transition
timestamps; cancelled and expired distinct.

API: POST /api/v1/bookings/estimate, POST /api/v1/bookings,
GET /api/v1/bookings/{public_code}, GET /api/v1/bookings (caller's own
bookings, newest first, limit param 1-100, default 20). Fare is computed
server-side from the vehicle_types table and snapshotted onto each booking.
Vehicle capacity is enforced server-side in create_booking (422 if
approx_weight_kg exceeds the vehicle type's capacity_kg) and filtered out of
/estimate's options (approx_weight_kg is an optional field there).

Auth: Firebase phone OTP end to end. Client uses FirebaseAuthRepository behind
the AuthRepository interface. Server verifies ID tokens via firebase-admin;
get_current_user is the only source of caller identity. Bookings enforce
ownership and return 404 (not 403) for another user's booking.
POST /bookings/estimate stays public by design.
Service account key at volt-backend/secrets/ — gitignored, never commit.
Both apps' google-services.json IS tracked, deliberately: client identifiers,
not secrets — they ship inside every compiled APK, and ignoring the file
breaks a fresh clone's build. Don't re-add an ignore rule for it.

Deployed: backend live at https://volt-api-951s.onrender.com (Render free
plan). Pushing to main auto-deploys to production, ~2 min. Render's free
Postgres expires ~30 days after creation (created 2026-08-08) — check the
Render dashboard for the exact date. When it expires, schema and seed data
rebuild fine from migrations, but all bookings and users are lost.

Driver endpoints (spec 008, merged to main and live in production):
drivers/{register,me,me/availability,jobs,bookings} and
bookings/{code}/{accept,pickup,deliver,cancel}. Driver identity is a second
Firebase principal (get_current_driver, app/driver_auth.py) — same token,
separate drivers.firebase_uid, no auto-create on first sight (must register).

Matching: job board. All online drivers with a matching vehicle_type_code see
every unclaimed pending booking; first to accept wins. No dispatch, no
per-driver assignment.

State machine (app/services/booking_lifecycle.py): pending -> driver_assigned
-> picked_up -> delivered, plus cancelled/expired off pending or
driver_assigned. picked_up cannot be cancelled (support problem, not
self-service). IllegalTransition and BookingAlreadyClaimed both map to 409 —
same status code, different meaning: one is "that move isn't legal from here",
the other is "you lost a race for this specific one."

Atomic claim (claim_booking in app/services/booking.py): the pending/unclaimed
check lives only in the UPDATE's WHERE clause, never in a prior SELECT —
that's what makes two simultaneous Accepts resolve to exactly one winner
without app-level locking. Depends on READ COMMITTED (Postgres's default):
the loser's UPDATE blocks on the winner's row lock, then re-evaluates WHERE
against the committed row and matches nothing. Under REPEATABLE READ or
SERIALIZABLE this would raise a serialization error instead and need retry
handling — don't raise the isolation level without adding that.

Expiry is lazy AND throttled: expire_stale_bookings() runs at the top of GET
/jobs, GET /bookings/{code} and GET /bookings, but at most once per 60s per
process (SWEEP_MIN_INTERVAL_SECONDS, module-level state in
app/services/booking.py). Polling forced this — every open screen was
dragging a write transaction behind every request, ~12/minute per active
user, almost all matching zero rows. Per-process is deliberate: N instances
each sweep independently, which is still a ~12x cut and harmless because the
UPDATE is idempotent. Tests reset it via reset_expiry_throttle() in an
autouse conftest fixture; without that, the first test to sweep suppresses
sweeping in every test for the next minute, order-dependently.

The sweep's predicate (status='pending' AND created_at < cutoff) is served by
ix_bookings_pending_created_at, a partial index on created_at WHERE
status='pending'. ix_bookings_status alone was never a seq scan, but it could
only satisfy the status half: the plan bitmap-scanned every pending row and
then filtered them all out. Measured on 200k rows / 5k pending / none
expirable — the steady state — that was 5006 buffers and 4.7ms to update zero
rows, scaling with pending count. With created_at in the index: 2 buffers,
0.055ms.

The effective window is "5 minutes plus however long until the next request,"
not 5 minutes.
Confirmed in real data: three bookings created minutes apart all came back
with the same expired_at, because nothing hit the API in between and one
sweep caught all three. Known debt — replace with a scheduled job once
there's real traffic to justify it. claim_booking distinguishes losing to
another driver (BookingAlreadyClaimed) from losing to this sweep
(BookingExpired) so a driver is never told "someone else took it" when
nobody did.

Going offline is blocked (409) while a driver holds a driver_assigned or
picked_up booking — going dark mid-job would strand a customer.

Double-accept is now closed (follow-up to spec 008, merged to main). A
driver can hold at most one driver_assigned/
picked_up booking, enforced by a partial unique index —
one_active_booking_per_driver on bookings(driver_id) WHERE status IN
(driver_assigned, picked_up) — the same reasoning as the atomic claim above:
a SELECT-based pre-check alone has the identical race (two simultaneous
accepts by the same driver, on different bookings, can both read "no active
booking" before either commits). claim_booking does the pre-check for a
friendly message, then catches the IntegrityError the index raises if the
pre-check missed the race, both mapping to DriverHasActiveBooking -> 409.

Driver app (spec 010, complete, merged to main, deployed). Package id
in.volt.driver. Happy path verified on device against the deployed backend:
booking created, accepted, picked up, delivered. GET /api/v1/vehicle-types
and every driver endpoint are live in production, so the customer app finally
has a real counterpart to match against.

Spec 010 negative cases, verified locally:
- Vehicle-type filter works — a Mini-Truck booking is not shown to a Bike
  driver.
- Expiry works — an unclaimed booking comes back status=expired with
  expired_at set.
- One-active-job is not reachable from the UI by design: the job board hides
  itself while a driver holds a job, so there is no second Accept to press.
  The invariant is proven at the layer that actually enforces it — the
  partial unique index, exercised by the forced-contention concurrency test.

Polling (spec 011). 5 second interval, in both apps, via Poller in
volt_core. Interim by design — it is a stand-in for FCM push in phase 3, not
the destination. Every watcher must be autoDispose: AsyncNotifierProvider is
keep-alive by DEFAULT in Riverpod 3, and declared the obvious way a watcher
outlives its screen and polls a finished booking until the app is killed.

Stop conditions, which are three different things and must not be merged:
terminal status stops permanently (Poller.stopForever, never re-armed);
backgrounding is only a pause (re-arms on resume with an immediate fetch);
disposal is structural. A tick is skipped, never queued, while a request is
in flight — on a cold-started free tier one request can take 50s against a
5s interval. That guard also means only one request is ever outstanding, so
responses cannot arrive out of order and nothing needs a sequence counter.

A failed poll must never clear the last known good state. First load fails
-> real AsyncError with Riverpod retry (safe, it is a GET). Later poll fails
-> booking untouched, only a failure counter moves, and the screen shows a
"not updating" hint after three misses. This is the exact opposite of
create-booking and accept, which are mutations and must never sit in a
provider at all.

Pickup, deliver and cancel are idempotent when the booking is already in
the status asked for: 200 with the existing row, not 409. These endpoints
mean "put this booking into state X", so if it is already in X the caller's
intent is met. The case it exists for is not a UI double-tap but a request
that succeeded here and timed out at the client — routine on a 50s cold
start over mobile — where the only sane retry is the same request. Nothing
is written on that path (the conditional UPDATE matched zero rows), so
picked_up_at and friends keep their original values by construction. The
decision is made from the re-read AFTER the UPDATE, never a pre-check, which
would reintroduce the race claim_booking exists to close.

Deliberately NOT accept: that means "claim this for ME", not "set status to
driver_assigned", so a booking held by another driver must stay 409. Also
NOT cancel-after-pickup — the goods are with the driver, which is a support
problem. Both are covered by tests.

IllegalTransition carries two messages. str(e) is for the log; user_message
is the only one that may leave the server, keyed on the booking's current
status. This is not cosmetic: Python 3.14 renders f"{BookingStatus.picked_up}"
as "BookingStatus.picked_up", and that string was reaching drivers.

Response schemas are per audience, not per model. Customers get
BookingDetailResponse (driver details + lifecycle timestamps); drivers get
the narrower BookingResponse. Do NOT add driver contact fields, or anything
customer-facing, to BookingResponse — the driver app reads the same object.
A test asserts the driver endpoints return exactly BookingResponse's key set.

The customer sees the driver's phone; the driver never sees the customer's.
Deliberately one-directional until masked two-way calling exists. And the
driver's phone is nulled once the booking is terminal — delivered, cancelled
or expired: operational data during a live trip, standing PII afterwards. On
a cancelled-after-assignment booking the customer still sees name and
vehicle number (who cancelled on them is their business) but not the number.
Enforced by a model_validator on the schema, not per call site.

Booking.driver is lazy="raise" on purpose. Async SQLAlchemy cannot lazy-load
a relationship mid-attribute-access, so without it a forgotten eager load
surfaces as MissingGreenlet inside a response serialiser, nowhere near the
cause. Every read path must ask: selectinload(Booking.driver).
get_booking_with_driver is separate from get_booking_by_code so the four
driver mutation paths don't pay a query for a field they never touch.

Real addresses (spec 012, merged to main and live in production). The six
hardcoded Bengaluru locations are gone; pickup and drop come from Places
autocomplete, a dropped pin, or the device location button.

The address picker is one screen with two modes sharing ONE search field,
controller, debounce timer and session token — the field sits outside the
mode switch precisely so there is only ever one token, since an unmatched one
is billed as if there were none. Search mode returns the chosen place; map
mode pans to it so the pin can then be moved onto the actual gate. It opens
in map mode when something is already selected (so the existing pin is
visible) and in search mode when nothing is.

Location permission is requested on the button tap, never on screen open: a
dialog that appears as a screen loads gets dismissed reflexively, and on
Android a reflexive deny is one tap from deniedForever. Services-off,
denied and deniedForever are three different messages with three different
remedies (device location settings vs APP settings vs just tap again), and
none of them blocks the picker — search always still works. Permissions are
FINE + COARSE only; background location is deliberately absent because it
would need a Play Store declaration for something we never use.

Service area is env-driven on purpose: SERVICE_CENTER_LAT/LNG and
SERVICE_RADIUS_KM, exposed by public GET /api/v1/service-area. The radius can
be narrowed for a field test from the Render dashboard with no deploy and no
app rebuild, because both apps read it rather than hardcoding it. Enforced in
create_booking (not the route) so no future route can skip it; /estimate
checks in the route because estimate_all owns coordinates, not the request.
Straight-line distance, never road distance — the area asks "how far from
centre", not "how far to drive", so it must not move when ROAD_FACTOR does.
Boundary is inclusive.

Google is called ONLY from the backend, via authenticated POST endpoints at
/api/v1/places/{autocomplete,details,reverse-geocode}. This is not a
preference: an Android application restriction does not apply to the Places
or Geocoding web services (verified — Google answers REQUEST_DENIED "not
authorized... with empty referer"), so a client-side key would have to be
unrestricted and would ship extractable inside every APK. GOOGLE_MAPS_API_KEY
is server-side, application restriction NONE, API-restricted to Places API
(New) + Geocoding, with per-API quota caps as the thing that actually bounds
damage. Missing key gives 503, not a crash.

The separate Android key stays in customer_app's AndroidManifest for the map
widget only — Maps SDK for Android is what Android restrictions are for. It
is the same value already in google-services.json, so committing it adds no
exposure.

Authenticated, unlike POST /bookings/estimate which is public. The split is
who pays: price discovery costs a haversine, these cost money per call with
Google, and an open Places proxy is free autocomplete for anyone reading the
app's traffic.

Session tokens: one per search, generated client-side, sent on every
autocomplete call AND on the final details call — that last one is what
closes the session and bundles the whole search into ONE charge. Omitted or
reused, every keystroke-batch is billed separately. It is a body field on
autocomplete but a query param on details. Never reuse a token for a second
search.

place_id is stored on bookings but unread. It cannot be back-filled, and it
is the only Google content the Maps Platform terms allow storing
indefinitely — coordinates get 30 days, everything else (addresses,
autocomplete predictions) cannot be cached at all. That is why
place_coordinates has no address column, and why purge_expired issues a real
DELETE at 29 days rather than filtering stale rows on read.

The coordinate cache is consulted ONLY when there is no session token. A
token means a live search whose details call must reach Google to close the
billing session; serving that from cache would save one call and buy several
unbundled autocomplete charges. Its read path is therefore dormant until
something re-resolves a saved place_id; the write path runs now.

Coordinates are stored under BOTH the requested and the returned place id
when they differ, which they routinely do: Place Details answers with
Google's canonical id, and for an address-type prediction (the long "EkY..."
blobs autocomplete gives for a street or building, as opposed to a "ChIJ..."
establishment) that is not the id that was asked for. Writing only one of
them meant writing a key nothing would ever look up. Found by calling the
real API — a stub that echoes back its own argument cannot show this.

Fare still uses haversine x 1.4. Distance Matrix is spec 014.

Nothing in VOLT is rate limited. Deliberately deferred to its own spec rather
than done on the Places endpoints alone, which would leave /estimate exposed
while looking covered — and a per-user counter in Postgres would recreate the
write amplification the expiry throttle just removed. Waits for Redis in
phase 3. Each proxy call logs the caller id so that spec can pick a threshold
from evidence.

Crash reporting (spec 013 Part A). Crashlytics in both apps, wired in
volt_core (src/observability/) rather than per app so the two cannot drift.
All three error paths are covered: FlutterError.onError for framework errors,
PlatformDispatcher.instance.onError for async errors that never reach the
framework — the one most often missed, and where most real crashes live —
and native crashes automatically via the Gradle plugin.

PlatformDispatcher's handler MUST return true. Returning false re-raises to
the platform, which on Android kills the process; reporting a crash would
cause one.

Release-only by collection, not by wiring: handlers are always installed and
setCrashlyticsCollectionEnabled(!kDebugMode) switches off the upload. Gating
the handler assignments instead would make the error path differ between
debug and release, so a bug in a handler would only ever show up in the build
you cannot debug. Debug console output is unaffected.

Crash reports carry the Firebase uid and NOTHING else identifying. Never a
phone number, name or address, and never a booking code — a code resolves to
an address through our own database, which makes it PII one step removed.
Custom keys are app, api_base_url, and booking_status (written on change
only, not on every 5s poll). The uid is set in SessionNotifier, including the
restored-session path, which is what most launches take.

The test-crash button lives behind --dart-define=CRASH_TEST=true, not
kDebugMode: collection is off in debug so a debug-only button could never
produce a report, and a dart-define keeps it out of every ordinary build by
construction.

iOS has no dSYM upload phase, so native iOS traces would be
unsymbolicated. Left unconfigured rather than guessed at — Android is the
only platform being built.

Adding firebase_crashlytics forced firebase_core to 4.14.0, which
firebase_auth 6.5.7 cannot compile against. firebase_auth is now 6.6.1.
Adding one Firebase package can require moving another.

Crashlytics pulls com.google.firebase:firebase-measurement-connector:20.0.1
transitively — confirmed with `gradlew :app:dependencies`, whose parent chain
is firebase-crashlytics directly. It is an interop shim, not Analytics: no
firebase-analytics and no play-services-measurement* artifact is in the tree,
no firebase_analytics Dart package exists, and every google-services.json has
an EMPTY analytics_service block. So the apps ship no Analytics collection
code, and the "do NOT add analytics" guardrail holds.

The console's Logs & Breadcrumbs tab nonetheless shows screen_view,
session_start and initialized_rh_api attributed to Analytics. firebase-sessions
(also pulled by Crashlytics) accounts for session grouping, and
initialized_rh_api is not a documented Firebase Analytics event name, which
points at Firebase/Play-services internals rather than anything we declare.
Not fully explained from the repo side — see the note in
docs/specs/013 for how to settle it. Breadcrumbs carry no PII either way,
which is the part that matters, and the connector cannot be excluded without
breaking Crashlytics.

Verified on device (step D). Recorded because "it is merged, so it probably
works" is not evidence, and a year from now nobody will remember which parts
were actually exercised on a phone as opposed to only under test.

Spec 011 — polling + driver details:
- Customer screen advances within ~5s of a status change, with no manual
  refresh.
- Driver notices a customer cancellation within ~5s, without navigating away
  from the active job screen.
- Polling STOPS on a delivered booking, confirmed in the server logs — no
  repeating requests for that code. This was the check most likely to fail
  silently, since a leaked poller looks fine in the UI.

Spec 013 Part A — Crashlytics (release build, real device):
- Test crash reported, stack trace readable, R8 mapping id present.
- PII check passed: Keys shows only api_base_url and app; no phone number in
  any field. booking_status was absent as expected — the crash was triggered
  from the booking home screen, which never sets it.
- Rebuilt without --dart-define=CRASH_TEST and confirmed the button is not
  merely hidden but compiled out: the string "Force a test crash" is present
  in all three libapp.so ABIs in the CRASH_TEST build and absent from every
  .so, .dex and asset without it. bool.fromEnvironment folds to a const, so
  the tree-shaker removes the widget entirely.

Spec 012 — real addresses:
- Autocomplete, map pin drop, current location, service-area rejection, and a
  full booking with real addresses all pass.
- Run against the local server on the branch, then re-run against production
  after the merge — so the deployed key, its restrictions and its quota caps
  are all confirmed working, not just the local ones.
- Real addresses render correctly on the driver job board, which is the one
  cross-app consequence of dropping the six hardcoded locations.

Known gaps:
- Lazy expiry has no scheduled sweep (see above).
- Release APKs are debug-signed for both apps — neither can go to the Play
  Store until there's a real signing config. This is spec 013 Part B, and it
  is DEFERRED on purpose rather than pending:
  * The upload key is permanent in effect. Android only installs updates
    signed by the same key, so it wants creating when there is a real upload
    to verify against and the whole flow — keystore, Play App Signing, and
    the third fingerprint Google's own app-signing key adds — can be done and
    checked in one sitting. Generating it months early means a key and a
    password to look after with nothing depending on them yet.
  * Nothing is blocked meanwhile. Sideloaded debug-signed APKs install and
    run fine, which is the only distribution happening today.
  * Half-doing it is worse than not starting. A release build signed with a
    new upload key has a DIFFERENT SHA-1, and Firebase phone auth silently
    fails until that fingerprint is added — so set up and left untested it
    would look finished and break precisely when it mattered.
- No rate limiting anywhere (see above). The Google-side per-API quota cap
  is currently the only thing bounding spend if a client misbehaves.
- Reverse geocode is uncached by necessity, so a customer who drags the map
  a lot spends a billable call per settle. The on-idle trigger is the only
  mitigation.
- Nothing verified on device is re-verified automatically. See the
  device-verification record above; anything not listed there has only been
  proven by tests and analysis, not on a phone.