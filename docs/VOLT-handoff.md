# VOLT — Handoff

Porter-style on-demand logistics for Bengaluru. Customer app, driver app,
FastAPI backend, PostgreSQL. Solo founder, final-year CE student, small team of
friends helping.

Read this with `CLAUDE.md` (conventions + current state) and `docs/specs/`
(numbered specs, each recording *why*).

---

## Repo state — 2026-09-05

| | |
|---|---|
| Branch | `feat/road-distance` |
| Head | `9c8ab9b` feat(backend): real road distance from the Routes API — spec 014 |
| vs `origin/main` | **1 commit ahead, unpushed** |
| Working tree | clean, except this file |
| Backend tests | 154 passing |
| Flutter | `volt_core` 8 tests; all three packages analyze clean |
| Migration head | `afbcf9152650` (applied locally, **not** in production) |

**`main` is at `41a19c2`** and includes everything through spec 013 Part A.
Pushing `main` auto-deploys, so spec 014's two schema changes reach production
the moment this branch merges.

**THIS FILE IS UNTRACKED.** `git status` shows `?? docs/specs/VOLT-handoff.md`.
It is the one artifact of the last two sessions that is not in version
control, so it is also the one that vanishes with a bad `git clean`. Commit it.

Note the path: the file lives at `docs/specs/VOLT-handoff.md`, not
`docs/handoff.md`.

---

## Built and deployed

**Backend** — FastAPI, async SQLAlchemy, asyncpg, Alembic. Live at
`https://volt-api-951s.onrender.com`. Push to `main` auto-deploys in ~2 min.
~154 tests.

**Customer app** (`in.volt.customer`) — Firebase phone OTP, address search via
Places autocomplete and map pin drop, current location, vehicle selection with
server-computed fares, booking creation, live status polling with driver
details, cancel.

**Driver app** (`in.volt.driver`) — phone OTP, registration (name, vehicle
number, type), online/offline, job board polling, atomic job claiming,
pickup/deliver lifecycle.

**`packages/volt_core`** — shared Dart: `ApiClient` with auth interceptor and
error translation, auth repositories and providers, theme, `AppConfig`,
`Poller`, crash reporting.

**Database** — `users`, `drivers`, `vehicle_types`, `bookings`,
`place_coordinates`. Money in integer paise throughout.

**Crashlytics** — both apps, release builds only, uid-not-phone.

### Endpoints

| Method | Path | Auth |
|---|---|---|
| GET | `/api/v1/health` | none |
| GET | `/api/v1/service-area` | none |
| GET | `/api/v1/vehicle-types` | none |
| POST | `/api/v1/bookings/estimate` | none — price discovery is public by design |
| POST | `/api/v1/bookings` | customer |
| GET | `/api/v1/bookings` | customer |
| GET | `/api/v1/bookings/{code}` | customer, ownership enforced |
| POST | `/api/v1/bookings/{code}/cancel` | customer |
| POST | `/api/v1/bookings/{code}/accept` | driver |
| POST | `/api/v1/bookings/{code}/pickup` | driver |
| POST | `/api/v1/bookings/{code}/deliver` | driver |
| POST | `/api/v1/drivers/register` | token, no driver row yet |
| GET | `/api/v1/drivers/me` | driver |
| PATCH | `/api/v1/drivers/me/availability` | driver |
| GET | `/api/v1/drivers/jobs` | driver, online only |
| GET | `/api/v1/drivers/bookings` | driver |
| POST | `/api/v1/places/autocomplete` | authenticated |
| POST | `/api/v1/places/details` | authenticated |
| POST | `/api/v1/geocode/reverse` | authenticated |

---

## Half-built / in flight

**Spec 014 — real road distance.** Complete on branch `feat/road-distance`,
**not merged**. Google Routes API `computeRoutes`, `TRAFFIC_AWARE`, with a
haversine fallback. **No cache** — see the closed question below; one was
built and then removed for licence reasons. Blocked on two things:

1. Step C **row 5 only** (fares vs before, on real routes) plus the on-device
   fare comparison. Rows 1–4 and 6 are covered by the backend tests,
   including row 3 — the deliberate-outage case — which has 12 of them. Row 6
   (service-area rejection still straight-line) is test-covered.
2. Merge and deploy. **One** migration rides along: `afbcf9152650`
   (`bookings.distance_source`). Additive and safe on the live table.

Because there is no cache, a booking costs **two** live Routes requests — one
to estimate, one for create_booking's server-side recompute — both on the Pro
SKU. That is the correct price for not trusting a client-supplied distance,
but it means rate limiting matters more than it did, and the Google-side
quota cap is currently the only thing bounding spend.

**A spend guard exists in `tests/conftest.py`, and it must stay.**
`create_booking` calls the Routes API on every booking, `volt-backend/.env`
holds a live key, and with the cache gone nothing absorbs a repeat — so
without the autouse `_block_outbound_routing` fixture the suite bills real
Pro-tier requests. It patches `app.services.routing.default_routing_service`,
leaving `GoogleRoutingService` real for the tests that mock its HTTP layer.
Anyone adding a test needing real routing behaviour should mock httpx, not
disable this.

**Every caller reaches the routing service through the module**
(`routing.default_routing_service()`), never `from ... import
default_routing_service`. That is load-bearing, not style. A from-import
binds the name into the calling module at import time, so patching it at its
definition site does nothing — and that is precisely how this guard silently
failed to engage on its first attempt: **49 tests were reaching the real
client while the suite looked green.** Caught by making the real client raise
and watching failures drop from 49 to 14 (the 14 being `test_routing.py`,
which constructs the client on purpose).

**Spec 013 Part B — release signing.** Deferred deliberately, not forgotten.
Reasoning is on the Known-gaps entry in `CLAUDE.md`: the upload key wants
creating against a real Play upload, nothing is blocked meanwhile since
sideloading works, and a new upload key changes the SHA-1 so phone auth fails
silently until Firebase has the fingerprint — set up untested it would look
finished and break exactly when it mattered.

---

## Open questions someone has to answer

**Crashlytics breadcrumbs attributed to Analytics.** The console's Logs &
Breadcrumbs tab shows `screen_view`, `session_start` and `initialized_rh_api`
sourced from Analytics, despite the "do NOT add analytics" guardrail. What is
proven from the repo: no `firebase_analytics` Dart package, no
`firebase-analytics` or `play-services-measurement*` Gradle artifact, and an
empty `analytics_service` block in every `google-services.json` — so no
Analytics *collection* SDK ships and the guardrail holds. What does arrive is
`firebase-measurement-connector:20.0.1`, pulled directly by
`firebase-crashlytics`; it is an interop shim and cannot be excluded without
breaking Crashlytics.

That accounts for the guardrail but not every event name. To settle it:
**Firebase console → Analytics → Realtime/DebugView.** No data stream for
either app means nothing is collecting and the list is Firebase's own session
instrumentation under the Analytics label. A stream showing app events would
mean something is reporting that the dependency tree says is not in the APK,
and that is worth chasing. Breadcrumbs carry no PII either way, which is the
part that matters — this is recorded rather than assumed because "no
analytics package was added" and "no analytics events exist" are different
claims and only the first is proven.

**Google's caching clause for distance/duration — CLOSED, 2026-09-05.**
Answered by reading the primary text: Service Specific Terms **s19 (Routes
API)** permits caching **latitude and longitude only**, 30 days. Distance and
duration are absent, and the master ToS prohibits caching Google Maps Content
except where expressly permitted, so unlisted means forbidden. **s11.8**
grants distance and duration caching for the Navigation Connect API, which
shows the omission from s19 is deliberate.

The route cache has been removed accordingly — table, model, migration,
service and tests. Do not reopen this. The secondhand quotations that
suggested otherwise were describing a different section.

---

## Locked decisions

Do not revisit these without a strong reason. Each has a cost attached to
changing it.

**Money is integer paise**, columns suffixed `_paise`. Floats accumulate error;
Razorpay takes paise, so no conversion boundary.

**Bookings snapshot their quoted rates** (`quoted_base_fare_paise`,
`quoted_per_km_paise`, `quoted_included_km`, `quoted_min_fare_paise`). Changing
`vehicle_types` must never rewrite what a past booking appears to have cost, or
GST invoices stop reconciling.

**`cancelled` and `expired` are distinct.** One is a customer choice, the other
a supply failure. Merging them destroys the only metric that says whether there
are enough drivers.

**Status is derived from per-transition timestamps.** Every transition writes
its own column, so an impossible state is detectable.

**Public booking codes are random** (`VLT` + 8 chars from an alphabet excluding
0/O/1/I/L). Sequential ids let anyone count daily volume and probe other
customers' bookings.

**The server is authoritative on fare.** The client sends coordinates and a
vehicle code, never a price. `LocalFareEstimator` survives as a display-only
offline fallback and must never produce a quote sent to the server.

**Job claiming is a single atomic conditional UPDATE**
(`WHERE status='pending' AND driver_id IS NULL`), never select-then-update.
Depends on Postgres READ COMMITTED; under REPEATABLE READ it would raise a
serialization error needing retry handling. An `asyncio.Lock` would not help —
it does not span uvicorn workers.

**One active booking per driver, enforced by a partial unique index**
(`WHERE status IN ('driver_assigned','picked_up')`). The application pre-check
exists only for a better error message.

**Pickup, deliver and cancel are idempotent** — requesting a state the booking
is already in returns 200 with the unchanged row, not 409. The driving case is
a request that succeeds server-side and times out client-side on a mobile
network, which has no correct client-side answer. **Accept is deliberately not
idempotent**: it means "claim this for me," and 409 carries information the
caller needs.

**Response schemas are per audience.** Customers see driver name, vehicle and
phone; drivers see no customer contact details. Never add driver contact fields
to the shared `BookingResponse`. A test asserts the driver-facing response key
set equals `BookingResponse.model_fields` exactly.

**Another user's booking returns 404, not 403.** A 403 confirms existence and
makes codes worth enumerating.

**Google Maps calls are proxied through the backend**, authenticated, using a
server-only key. Android application restrictions do not apply to the Places
*web service*, so a client-side implementation would need an unrestricted key
shipped inside the APK. Verified from the other side: the Android key returns
`REQUEST_DENIED` for web-service calls.

**Service area is configuration, not code** — `SERVICE_CENTER_LAT/LNG`,
`SERVICE_RADIUS_KM`. Currently 25km around ~12.9716, 77.5946. Deliberately
env-driven so it can be narrowed to a few km for a field test from the Render
dashboard with no deploy. It is a placeholder; real coverage eventually means
polygons in a table.

**Service-area checks use straight-line distance**, not road distance. "How far
from the centre," not "how far to drive." Only trip distance uses Routes.

**Client-side checks are UX, server-side are rules.** Applies to fare, service
area, and vehicle capacity alike.

**`lazy="raise"` on the `Booking.driver` relationship.** Converts an invisible
`MissingGreenlet` in a request handler into a loud failure at the point of the
mistake. Every access needs explicit `selectinload`.

**`google-services.json` is committed on purpose.** Client identifiers, not
secrets — extractable from any APK, and Firebase's model assumes it. Excluding
it just breaks teammates' builds. This was reversed once by mistake; if it
appears in `.gitignore` again, that is the regression.

**Booking creation and job acceptance must stay `ref.read` inside button
handlers, never providers.** Riverpod 3 auto-retries failed providers, which
would create duplicate bookings and claim jobs the driver did not choose.

---

## Known gaps

**No rate limiting anywhere.** Including `/estimate`, which is public and
unauthenticated and therefore the most attractive target. The only spend bound
is Google-side quota alerts. Deferred as needing its own spec — the design
decisions are cross-cutting (per-user vs per-IP, what a 429 does to a client
polling every 5s, different limits for customers and drivers), and a good
implementation wants Redis, which arrives in phase 3. A Postgres counter would
mean a write per request, which is the amplification pattern already removed
from the expiry sweep.

**Lazy expiry has no scheduler.** `expire_stale_bookings` runs on API requests,
throttled to once per 60s per process. If nobody calls the API, a booking sits
`pending` past 5 minutes until someone does. Observed in real data: three
bookings created minutes apart all received the same `expired_at`. Worse at low
traffic, not better.

**Release APKs are debug-signed.** Cannot go to Play Store. See spec 013 Part B.

**Zero Flutter tests.** 154 backend tests, none in either app. Every screen
change is verified by tapping through it manually.

**Driver verification is a stub.** `is_verified` is set true on registration.
No licence, RC, insurance or photo check. This is a hard blocker before any
driver who is not the owner does a delivery.

**Real SMS is off.** Only Firebase test numbers can sign in. Turning it on
needs a daily SMS quota cap and abuse protection (App Check, SMS region policy
restricted to India) — SMS pumping is a real attack. Console work, not code.

**No driver→customer contact.** Customers can call drivers; not the reverse. A
driver at a locked gate cannot call. Masked two-way calling is the proper fix,
phase 4.

**Render free Postgres expires.** Created 8 Aug 2026, ~30-day free window.
Schema and seed data rebuild from migrations; bookings and users would be lost.

**Free trial ends 3 Dec 2026.** Maps APIs stop working unless the Cloud billing
account is activated. Activating also removes the hard spending ceiling the
trial currently provides.

**iOS dSYM upload unconfigured.** Android-only builds, so untested and
deliberately not written.

---

## Planned, not built — pricing effort rather than geometry

Fares currently depend on distance alone. `_fare_paise` takes `distance_m` and
nothing else.

**Time-based component.** A 6km trip at 11pm and at 6pm cost the same despite
triple the driver's time. Planned as `per_minute_paise` on `vehicle_types`,
using the duration already returned by Routes. **Per-km must come down when
per-minute goes in**, not stay put, or it is a second fare rise.

**Waiting charges.** Time between `driver_assigned_at` and `picked_up_at` is
unpaid driver time. Industry norm is a free window then per-minute. Needs no
schema work — `final_fare_paise` exists separately from `quoted_fare_paise` for
exactly this.

**Proximity matching.** The job board is city-wide, so a Whitefield driver sees
a Koramangala pickup and eats the approach unpaid. Nobody charges the customer
for approach; the fix is matching by driver location, which needs phase 3 live
tracking. This is a matching problem — do not "fix" it with an approach fee.

---

## A finding worth keeping

Spec 014 measured five routes against the old haversine × 1.4:

Mean change **+0.6%**, range **−12.3% to +24.1%**, true road factor 1.23–1.74.
Koramangala → Whitefield came out 9.2% *shorter*, not longer.

1.4 was not wrong on average — it was wrong per route. It overcharged long
ring-road trips, which are efficient, and undercharged peripheral cross-town
trips by up to a quarter. No single multiplier fixes that, because the error
has opposite signs on different route shapes.

---

## Verification lessons

Five separate green-but-worthless tests were found in this project. All had the
same shape: **a fixture where two things were indistinguishable, so the test
could not detect using the wrong one.**

- Concurrency test where the calls never actually contended
- N+1 test where all bookings shared one driver, so the identity map hid the
  repeats
- Poller tests that watched callbacks stop, which the `_stopped` flag delivers
  whether or not the timer was cancelled
- Service-area boundary test that searched for a coordinate at exactly 25km,
  which by construction stops just inside
- Place cache test whose stub echoed its own argument, so storing under the
  resolved id and reading under the requested id looked identical

The habit: **after a test passes, break the thing it tests and confirm it goes
red.**

A sixth lesson of a different kind, from spec 014's migration: **a
migration file can look completely correct and still be wrong, and only
running it finds out.** Two faults in one autogenerated migration:
`op.add_column` with `sa.Enum` does **not** emit `CREATE TYPE` on PostgreSQL,
so the upgrade died on `type "distance_source" does not exist`; and the
generated downgrade dropped the column but left the type, so
downgrade-then-upgrade failed with "already exists". The habit that catches
both: **round-trip every migration — `upgrade`, `downgrade -1`, `upgrade`
again — before committing it.**

Cost of learning that: `alembic downgrade -1` on the shared dev database
dropped the local `place_coordinates` table. Cache-only, so nothing was lost,
but a downgrade on a dev DB is a destructive act and deserves the same pause
as one in production.

Three grep false positives, also one shape: **the search matched commentary
about the thing rather than the thing.** `git log | grep secrets/` matching a
commit message, an AndroidManifest grep matching a comment explaining why the
permission is absent, and `grep -qU $'\x00'` matching every file because bash
cannot hold a NUL.

---

## Working practices

- Every feature is a numbered markdown spec in `docs/specs/`, committed, then
  handed to Claude Code with explicit guardrails.
- Specs record why, including where the original assumption was wrong — spec
  012 has a "What actually shipped" section rather than a silently corrected
  body.
- Work happens on a branch. `main` auto-deploys to production, so nothing
  half-finished belongs there.
- `git status --short` before every commit; read the file list.
- Secrets never leave the machine they are used on. Not chat, not screenshots,
  not a scratch file. A service account key was pasted once and had to be
  rotated.

## Settled: the CRLF churn

Recorded because it recurred four times and looked like a missing config each
time. `.gitattributes` **already existed and was already correct**
(`* text=auto eol=lf` plus `binary` for png/jpg/ico/ttf/otf); `git check-attr`
confirms the rules are in effect, and `git add --renormalize .` across the
whole tree staged nothing but the file itself — meaning **no tracked file has
ever carried CRLF into a commit.**

The phantom `M` entries are a **stale stat cache**, not content churn:
Flutter rewrites the generated plugin registrants with platform line endings
on every `pub get`, their byte size changes, git flags them, and the diff then
normalizes to nothing. It will recur, it is cosmetic, and
`git checkout -- <paths>` clears it. A UTF-8 BOM was removed from
`.gitattributes` — git tolerates one, so it was never the cause.

## Environment

Windows 11, Realme RMX3371 (Android 14) as the test device, no emulator.
Flutter at `C:\dev\flutter`, PostgreSQL 18, Python 3.14. Repo at
`C:\Users\admin\projects\volt`, GitHub `shreyasgowda960-hub/volt` (private).

Run against local: `.\run-local.ps1` — needs `uvicorn app.main:app --reload
--host 0.0.0.0` and the LAN IP in the script kept current.
Run against production: `.\run-prod.ps1`.

Secrets: `volt-backend/.env` (gitignored) and Render's Environment tab.
`volt-backend/secrets/firebase-service-account.json` is the one real secret.

---

## Next task

**Finish and merge spec 014.** Owner verifies the caching clause, completes the
on-device fare comparison, merges to `main`.

Then, in order of value:

1. **Real SMS enablement** — App Check, SMS region policy limited to India,
   daily quota cap. Blocks anyone outside the test-number list from signing in.
2. **Driver document verification** — the hard blocker before a real driver.
   Good candidate to hand to a collaborator: cleanly separated, own schema,
   own screens.
3. **Time-based fare component** — see Planned above.
4. **Flutter tests** — the largest untested surface in the project.
5. **Live location tracking (phase 3)** — Redis, foreground service, proximity
   matching. Hardest remaining work; ColorOS background-kill behaviour on the
   test device is a known obstacle.

The learning plan at `docs/learning-plan.md` is six sessions over the existing
code, started and paused at session 1. The owner flagged building faster than
understanding as a concern and chose to keep building. Worth returning to at a
phase boundary.
