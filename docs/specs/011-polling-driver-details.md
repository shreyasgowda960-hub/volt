# Spec 011 — Live status: polling + driver details

Build mode. After this, VOLT stops needing manual refresh.

**Precondition:** spec 010 merged and deployed. Both apps verified against
production.

## New concepts introduced here

1. **Async lazy loading is a trap.** `booking.driver` on an async SQLAlchemy
   session raises `MissingGreenlet` if the relationship was not eagerly loaded
   — the ORM cannot issue a query mid-attribute-access without an `await`.
   Every relationship must be loaded explicitly with `selectinload`. On a list
   endpoint, forgetting this is also the classic N+1: one query for bookings,
   then one more per booking.
2. **Response schemas are per audience, not per model.** Customers see driver
   details; drivers do not see customer details. Two schemas over one table.
   Adding a field to a shared schema leaks it to every caller — which is why
   driver contact info must never land on `BookingResponse`.
3. **Polling has a lifecycle.** A timer that starts is easy; one that stops is
   the work. Stop on terminal status, stop when the app is backgrounded, never
   stack two timers, and never let a slow request overlap the next tick.
4. **`tel:` deep links.** Handing a phone number to the OS dialler rather than
   implementing calling.

## Guardrails

- **Do NOT add push notifications, FCM, WebSockets, or Redis.** Phase 3.
- **Do NOT add driver contact fields to `BookingResponse`.** New schema.
- **Do NOT show the customer's phone number to the driver.** Decided against
  for now.
- **Do NOT remove the manual refresh buttons.** Polling fails; the fallback
  stays.
- One new dependency, named in step 5. Nothing else.
- Branch. Tell me before pushing.

## Decisions being implemented

| Decision | Value |
|---|---|
| Poll interval | 5 seconds |
| Poll stops | Terminal status, or app backgrounded |
| Customer sees | Driver name, vehicle number, vehicle type, rating, **phone** |
| Driver sees | No customer contact details |

---

# PART A — Backend

## A1. Add the ORM relationship

`Booking` has `driver_id` as a foreign key but no `relationship()`, so there is
no way to traverse to the driver.

In `app/models/booking.py`, add a `driver` relationship to `Driver`, and the
reverse on `Driver` if useful. Use `lazy="raise"` on it.

**`lazy="raise"` is deliberate.** It makes any accidental un-eager access fail
loudly at development time instead of raising `MissingGreenlet` later in a
request handler where the cause is unobvious. Explain this in a comment.

No migration needed — a relationship is Python-side only, the column already
exists.

## A2. Customer-facing schema with driver details

**New in `app/schemas/booking.py`:**

```python
class AssignedDriverResponse(BaseModel):
    """Driver details shown to the CUSTOMER of a booking.

    Includes phone so the customer can call about access, gates, floors.
    Deliberately one-directional: the driver does not receive customer
    contact details. Masked two-way calling is the eventual fix.
    """
    model_config = ConfigDict(from_attributes=True)

    name: str
    phone: str
    vehicle_number: str
    vehicle_type_code: str
    rating: float | None


class BookingDetailResponse(BookingResponse):
    """BookingResponse plus the assigned driver. Customer endpoints only."""

    driver: AssignedDriverResponse | None
```

`driver` is null until assigned, and after `cancelled` or `expired` it stays
null. Do not invent a placeholder.

## A3. Use it on customer endpoints only

Change the response model to `BookingDetailResponse` on:

- `GET /api/v1/bookings/{public_code}`
- `GET /api/v1/bookings`

**Leave unchanged** — these are driver-facing and must not gain customer data:

- `GET /api/v1/drivers/jobs`
- `GET /api/v1/drivers/bookings`
- the accept / pickup / deliver endpoints

Grep afterwards to confirm `BookingDetailResponse` appears only on customer
routes.

## A4. Eager loading

Both customer endpoints must load the driver in the same query:

```python
select(Booking)
    .options(selectinload(Booking.driver))
    .where(...)
```

Without this, `lazy="raise"` fires immediately — which is the point of setting
it. The list endpoint is where `selectinload` earns its keep: one extra query
total rather than one per booking.

## A5. Tests

- `GET /bookings/{code}` on an unassigned booking → `driver` is null
- Same after a driver accepts → name, phone, vehicle number present
- `GET /bookings` with several bookings → driver populated where assigned, and
  **assert the query count** to prove no N+1. If counting queries is awkward
  in this setup, say so rather than skipping silently.
- `GET /drivers/jobs` response → contains **no** customer fields. Assert on
  absence; this is the privacy guarantee and it should be a test, not a
  convention.

---

# PART B — Customer app polling

## B1. New dependency

```powershell
cd $env:USERPROFILE\projects\volt\customer_app
flutter pub add url_launcher
```

**`url_launcher`** hands a URI to the OS. Used here for `tel:` so the Call
button opens the dialler. It replaces nothing — there is no other way to reach
the system dialler from Flutter.

Android 11+ requires a `<queries>` entry for `tel` intents in
`AndroidManifest.xml` or `canLaunchUrl` returns false. Verify against the
package's current README rather than assuming the exact form.

## B2. The polling notifier

Add to the booking feature. This is the part with real subtlety:

```dart
/// Polls a booking while its status can still change.
///
/// Stops permanently on a terminal status, pauses when the app is
/// backgrounded, and never allows two requests in flight — on a cold-started
/// free-tier backend a single request can take 50s, far longer than the 5s
/// tick, and without a guard the ticks would stack up.
class BookingWatcher extends ... {
  static const _interval = Duration(seconds: 5);
  bool _inFlight = false;
  Timer? _timer;
}
```

Requirements, all of them:

- Fetch immediately on start, then every 5 seconds
- **Skip a tick if the previous request is still in flight.** Do not queue it
- Stop the timer on `delivered`, `cancelled`, `expired` — permanently
- Pause on background, resume and fetch immediately on foreground. Use
  `AppLifecycleListener`
- Cancel the timer in `dispose`. An uncancelled timer calling into a disposed
  object is the same leak found in spec 007
- A failed poll must not clear the last known good state — the screen should
  keep showing the booking, not flash empty. Optionally show a small "not
  updating" hint after several consecutive failures

Riverpod 3's auto-retry is acceptable here: a GET is idempotent, so retrying a
failed poll is safe. That is the opposite of the accept and create-booking
calls, which must never live in a provider.

## B3. Status screen

Rewrite `booking_status_screen.dart` to consume the watcher.

**Timeline** — four steps: Booking placed, Driver assigned, Picked up,
Delivered. Completed steps get a tick, the current one is highlighted, future
ones are muted. Where a timestamp exists, show the time.

**Driver card**, once `driver` is non-null: name, vehicle number prominently
(it is what the customer looks for in the street), vehicle type, rating if
present, and a **Call** button launching `tel:`.

**Terminal states:**

- `delivered` — a clear completion state, final fare, no spinner
- `cancelled` — who cancelled and the reason if present
- `expired` — "No driver was available" with a **Book again** action. This is
  the state that tells the customer something went wrong on your side, so the
  wording matters: not an error, an apology with a next step

**Keep the manual refresh button.** Polling fails.

## B4. Cancel

The backend has `POST /bookings/{code}/cancel` and no app ever calls it. Add a
**Cancel booking** button, visible only while `pending` or `driver_assigned`.

Confirmation dialog first. On success the watcher picks up the new status
naturally. Per the phase 1 decision cancellation is free before pickup, so no
fee messaging — and after pickup the button must not appear at all, because the
server will reject it with 409.

---

# PART C — Driver app polling

## C1. Job board

Same mechanism, mirrored: poll `GET /drivers/jobs` every 5 seconds while the
driver is **online and has no active job**. Stop when offline, stop when a job
is active, pause on background.

Extract the polling logic into `volt_core` if it comes out cleanly — both apps
now need it, and this is exactly the duplication the package exists to prevent.
If the two cases differ enough that sharing would mean parameterising heavily,
duplicate and say so.

New jobs should appear without the driver touching anything. That is the
difference between a job board a driver leaves open and one they abandon.

## C2. Active job

Poll the active job every 5 seconds too — the customer may cancel while the
driver is en route, and a driver driving to a cancelled pickup is the worst
outcome in the system.

On detecting a cancellation, show it clearly and return to the board.

---

## Step D — Verify on device

Both apps against **production**. The point of this spec is that you touch
nothing:

| Test | Expected |
|---|---|
| Customer creates booking, leaves screen open | Stays "Finding a driver" |
| Driver online, board open, customer books | Job appears within ~5s, no tap |
| Driver accepts | Customer screen updates within ~5s, driver card appears |
| Customer taps Call | Dialler opens with the driver's number |
| Driver marks picked up | Customer timeline advances within ~5s |
| Driver marks delivered | Customer shows completion, polling stops |
| Background the customer app 2 min, reopen | Immediate refresh, correct status |
| Customer cancels while driver assigned | Driver app notices within ~5s |
| Unaccepted booking after 6 min | Customer sees expired with Book again |

**Then check polling actually stops.** With a delivered booking on screen,
watch the uvicorn or Render logs for a minute — no repeating requests for that
code. A poll that never stops is the bug this spec is most likely to ship.

## Step E — Update `CLAUDE.md`

Polling interval and stop conditions, the customer-sees-driver / driver-does-
not-see-customer asymmetry and why, `lazy="raise"` and the eager-loading
requirement, and that polling is interim until FCM in phase 3.

## Step F — Report and stop

1. Files created and edited across all three targets
2. The step D table with real results
3. Whether the polling logic was extracted into `volt_core` or duplicated, and
   why
4. Confirmation that no driver-facing response contains customer data, and
   whether that is covered by a test
5. Whether you could assert query counts for the N+1 test
6. Anything you were tempted to build and did not

Do not push.
