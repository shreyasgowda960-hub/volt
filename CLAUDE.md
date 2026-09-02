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
  customer_app/        # Flutter — building this first
  driver_app/          # Flutter — later
  admin-dashboard/     # React + TS — later
  volt-backend/        # FastAPI — later
```
Flutter folders use underscores because Dart package names cannot contain hyphens.


## Current state — keep this updated
Phase 1, customer app. Working on device (RMX3371, Android 14).
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
Server must run with --host 0.0.0.0 for the phone to reach it.
Booking status screen shows the real, persisted status (currently always
`pending` — no driver app exists yet) with a manual refresh button. No
polling — that's spec 007.

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

Deployed: backend live at https://volt-api-951s.onrender.com (Render free
plan). Pushing to main auto-deploys to production, ~2 min. Render's free
Postgres expires ~30 days after creation (created 2026-08-08) — check the
Render dashboard for the exact date. When it expires, schema and seed data
rebuild fine from migrations, but all bookings and users are lost.

Driver endpoints (spec 008, on branch feat/driver-endpoints — not yet merged
to main): drivers/{register,me,me/availability,jobs,bookings} and
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

Expiry is lazy: expire_stale_bookings() runs at the top of GET /jobs, GET
/bookings/{code}, and GET /bookings, not on a schedule. A pending booking can
sit stale past 5 minutes indefinitely if nothing calls the API in the
meantime — known, accepted limitation until there's real traffic to justify a
scheduled job. claim_booking distinguishes losing to another driver
(BookingAlreadyClaimed) from losing to this sweep (BookingExpired) so a
driver is never told "someone else took it" when nobody did.

Going offline is blocked (409) while a driver holds a driver_assigned or
picked_up booking — going dark mid-job would strand a customer.

Double-accept is now closed (follow-up to spec 008, still on
feat/driver-endpoints). A driver can hold at most one driver_assigned/
picked_up booking, enforced by a partial unique index —
one_active_booking_per_driver on bookings(driver_id) WHERE status IN
(driver_assigned, picked_up) — the same reasoning as the atomic claim above:
a SELECT-based pre-check alone has the identical race (two simultaneous
accepts by the same driver, on different bookings, can both read "no active
booking" before either commits). claim_booking does the pre-check for a
friendly message, then catches the IntegrityError the index raises if the
pre-check missed the race, both mapping to DriverHasActiveBooking -> 409.