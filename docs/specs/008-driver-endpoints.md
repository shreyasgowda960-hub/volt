# Spec 008 — Driver endpoints

Build mode. Backend only. The driver app is spec 009.

**Precondition:** spec 007 complete and deployed. `pytest` clean.

## New concepts introduced here

Read this before the code — these five ideas are why the spec is shaped the
way it is.

1. **Race conditions.** Two drivers tap Accept at the same moment. Read-then-
   write ("check it's unclaimed, then claim it") loses the race, because both
   read `pending` before either writes. The fix is a single atomic statement.
2. **Atomic conditional UPDATE.** `UPDATE … WHERE status = 'pending'` lets the
   database decide the winner. Postgres serialises row updates, so exactly one
   caller gets `rowcount == 1` and everyone else gets `0`. No application-level
   locking needed.
3. **409 Conflict.** A status code you have not used yet. Not the caller's
   fault (400/422) and not a permission problem (403) — the request was valid
   but the world changed underneath it. "Someone else took this job."
4. **State machines.** A booking can only move along legal edges:
   `pending → driver_assigned → picked_up → delivered`. Illegal transitions
   are rejected explicitly rather than silently allowed.
5. **Lazy expiry.** Marking bookings expired needs something to run on a
   schedule. Rather than adding a scheduler now, expiry is computed and applied
   when the API is touched. Simpler, with a real limitation named below.

## Guardrails

- **Do NOT build the driver Flutter app.** That is spec 009.
- **Do NOT add live location, Redis, or Google Maps.** Phase 3.
- **Do NOT add new dependencies.**
- Every driver-facing endpoint takes identity from the verified token. Nothing
  caller-supplied ever decides which driver is acting.
- Tell me before pushing — push to `main` auto-deploys to production.

## Decisions being implemented

| Decision | Value |
|---|---|
| Matching | Job board. All online drivers with a matching vehicle type see all pending bookings; first to accept wins. |
| Verification | Auto-verified on registration. `is_verified` stays in the schema for later. |
| Expiry | 5 minutes unaccepted → `expired` |
| Driver identity | Same Firebase project as customers, separate `drivers` row keyed on `firebase_uid` |

---

## Step 1 — Migration: link drivers to Firebase

`drivers` has no `firebase_uid`, so there is no way to identify the caller.

New Alembic migration adding to `drivers`:

- `firebase_uid` — `String(128)`, unique, indexed, **nullable** (existing rows
  have none)

Generate with `--autogenerate`, read it before applying, then
`alembic upgrade head`.

## Step 2 — New file: `volt-backend/app/driver_auth.py`

A second authentication principal. `get_current_user` returns a customer;
this returns a driver. Same token, different table.

```python
async def get_current_driver(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Driver:
    """Verifies the Firebase ID token and returns the matching Driver row.

    Unlike get_current_user, this does NOT create a row on first sight —
    drivers must register explicitly, because a driver record needs a vehicle
    and a plate number that Firebase knows nothing about.
    """
```

Behaviour:

- Invalid or expired token → **401**
- Valid token, no `drivers` row for that uid → **403**, detail
  `"Not registered as a driver"`
- `is_verified` false → **403**, detail `"Driver account pending verification"`
- Otherwise return the `Driver`

Reuse the token-verification logic from `app/auth.py` rather than duplicating
it — extract a shared `verify_token(creds) -> dict` helper and have both
dependencies call it.

Note a phone number can legitimately be both a customer and a driver. Two
rows, two principals, same Firebase uid. That is fine and should not be
prevented.

## Step 3 — Booking state machine

**New file: `volt-backend/app/services/booking_lifecycle.py`**

Define the legal transitions in one place, as data:

```python
_LEGAL_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.pending: {
        BookingStatus.driver_assigned,
        BookingStatus.cancelled,
        BookingStatus.expired,
    },
    BookingStatus.driver_assigned: {
        BookingStatus.picked_up,
        BookingStatus.cancelled,
    },
    BookingStatus.picked_up: {BookingStatus.delivered},
    BookingStatus.delivered: set(),
    BookingStatus.cancelled: set(),
    BookingStatus.expired: set(),
}
```

Plus `IllegalTransition(Exception)` carrying the from/to states, and a
`can_transition(from, to) -> bool`.

Note `picked_up` cannot be cancelled — the goods are already with the driver,
so that is a support problem, not a self-service action. And `delivered`,
`cancelled`, `expired` are terminal.

Also define, in one place, which timestamp column each status sets:
`driver_assigned_at`, `picked_up_at`, `delivered_at`, `cancelled_at`,
`expired_at`. A status change must always write its timestamp — the schema was
designed so status is derivable from timestamps, and that only holds if this is
enforced.

## Step 4 — Lazy expiry

**In `volt-backend/app/services/booking.py`:**

```python
EXPIRY_MINUTES = 5


async def expire_stale_bookings(db: AsyncSession) -> int:
    """Marks pending bookings older than EXPIRY_MINUTES as expired.

    Called at the start of endpoints that read booking state rather than run
    on a schedule. Idempotent and cheap — one UPDATE against an indexed column.

    LIMITATION: if nobody calls the API, bookings stay pending past 5 minutes
    until someone does. Acceptable now; replace with a scheduled job when
    there is real traffic. Do not build the scheduler in this spec.
    """
```

Single `UPDATE bookings SET status='expired', expired_at=now() WHERE
status='pending' AND created_at < now() - interval`. Return the row count.

Call it at the start of: the job board endpoint, the customer's get-booking
endpoint, and the customer's list-bookings endpoint.

Use the **database's** clock (`func.now()`), not Python's — app servers and the
database can disagree, and with multiple instances they will.

## Step 5 — The atomic claim

**This is the correctness centre of the spec.** Get it exactly right.

In `volt-backend/app/services/booking.py`:

```python
async def claim_booking(
    db: AsyncSession, public_code: str, driver: Driver
) -> Booking:
    """Assigns a pending booking to a driver, atomically.

    Two drivers tapping Accept simultaneously both read status='pending'
    before either writes. A read-then-write would assign both. Instead the
    WHERE clause carries the precondition, so Postgres decides the winner:
    exactly one UPDATE matches a row, the rest match zero.

    Raises BookingAlreadyClaimed when this caller lost the race.
    """
    result = await db.execute(
        update(Booking)
        .where(
            Booking.public_code == public_code,
            Booking.status == BookingStatus.pending,
            Booking.driver_id.is_(None),
        )
        .values(
            driver_id=driver.id,
            status=BookingStatus.driver_assigned,
            driver_assigned_at=func.now(),
        )
        .returning(Booking.id)
    )
    claimed = result.scalar_one_or_none()

    if claimed is None:
        # Either it does not exist, or someone else got there first. Both
        # answer the same way to this caller.
        raise BookingAlreadyClaimed(public_code)

    await db.commit()
    ...
```

Also validate **before** the UPDATE: the driver's `vehicle_type_code` must
match the booking's, and the driver must be online. Do those as an explicit
check with a clear error, since failing them is a client bug rather than a
race.

**Do not** implement this as "select, check, update." Do not add a Python lock.
The single statement is the mechanism.

## Step 6 — Driver endpoints

**New file: `volt-backend/app/routers/drivers.py`**, prefix
`/api/v1/drivers`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/register` | Create the driver profile for the token's uid |
| GET | `/me` | Current driver profile and online status |
| PATCH | `/me/availability` | Go online / offline |
| GET | `/jobs` | Pending bookings matching this driver's vehicle type |
| GET | `/bookings` | This driver's own bookings, newest first |

**`POST /register`** takes name, `vehicle_number`, `vehicle_type_code`. Uses
`verify_token` directly rather than `get_current_driver` — the driver row does
not exist yet. Sets `is_verified=True` per the decision above, with a comment
saying so. Reject with 409 if a driver already exists for that uid.

**`GET /jobs`** — call `expire_stale_bookings` first, then return `pending`
bookings where `vehicle_type_code` matches the driver's and `driver_id` is
null, newest first, `limit` bounded 1–50. Return **403** if the driver is
offline: a driver who has not gone online should not be browsing jobs.

## Step 7 — Booking action endpoints

**In `volt-backend/app/routers/bookings.py`:**

| Method | Path | Actor | Purpose |
|---|---|---|---|
| POST | `/{public_code}/accept` | driver | Atomic claim |
| POST | `/{public_code}/pickup` | driver | `driver_assigned → picked_up` |
| POST | `/{public_code}/deliver` | driver | `picked_up → delivered` |
| POST | `/{public_code}/cancel` | customer | → `cancelled`, before pickup only |

Status codes, and be precise about these:

- Lost the race, or already claimed → **409**
- Illegal transition (e.g. deliver before pickup) → **409**
- Driver acting on a booking that is not theirs → **404**, not 403
- Customer cancelling after pickup → **409** with a clear message
- Vehicle type mismatch on accept → **422**

The 404-not-403 rule is the same reasoning as `GET /bookings/{code}`: a 403
confirms the booking exists, which makes codes worth guessing.

**Cancel** sets `cancelled_at` and `cancelled_by=customer`, and accepts an
optional `cancellation_reason`. Per the phase 1 decision, cancellation is free
before pickup, so there is no fee logic — say so in a comment, because its
absence otherwise looks like an oversight.

## Step 8 — Tests

This is the spec where tests earn their keep. Required:

**The race, tested properly.** Two concurrent `claim_booking` calls on the same
booking using `asyncio.gather` with two separate sessions. Assert exactly one
succeeds, one raises `BookingAlreadyClaimed`, and the booking has exactly one
`driver_id`. If this test cannot be made to actually contend, say so rather
than writing one that passes trivially.

**State machine:** every illegal transition rejected, every legal one allowed.
Table-driven over `_LEGAL_TRANSITIONS`.

**Expiry:** a booking created 6 minutes ago becomes `expired`; one created 4
minutes ago does not; an already-`driver_assigned` booking is untouched.

**Auth:** valid token with no driver row → 403. Offline driver hitting
`/jobs` → 403. Driver acting on another driver's booking → 404.

**Timestamps:** each transition writes its own timestamp column.

## Step 9 — Update `CLAUDE.md`

Include the matching model, the expiry rule and its limitation, the atomic
claim pattern, and a note that `IllegalTransition` and `BookingAlreadyClaimed`
both map to 409.

## Step 10 — Report and stop

1. Files created and edited, and the migration revision id
2. Test results, and specifically whether the concurrency test genuinely
   contends or is a weaker approximation
3. Any place you deviated, and why
4. Anything about the lazy-expiry approach you think will bite us

Do not push. Do not build the driver app.
