# Spec 010 — The driver app

Build mode. Second Flutter client. After this, a booking moves from customer to
driver end to end.

**Precondition:** spec 009 merged. `volt_core` in place, customer app verified
on device.

## New concepts introduced here

1. **A second Firebase app in one project.** Same Firebase project, second
   Android app with a different package name. Same SHA-1 registered again —
   fingerprints are per-app, not per-project. Each app gets its own
   `google-services.json` and `firebase_options.dart`.
2. **Three-state auth routing.** The customer app has two states: signed out,
   signed in. The driver app has three — signed out, signed in but no driver
   profile, fully registered. That middle state is a 403 from the server, and
   routing on it is the interesting part.
3. **A 409 is a normal outcome, not an error.** When two drivers tap Accept,
   one loses. That is the system working correctly. The UI must treat it as an
   expected branch (refresh the board, explain briefly) rather than as a
   failure state with a red error screen.
4. **Never trust the client's view of state.** The job board is a snapshot the
   moment it loaded. By the time a driver taps Accept, the booking may be
   claimed or expired. Do not navigate to the job screen until the server
   confirms the claim.

## Guardrails

- **Do NOT add status polling** to either app. That is spec 011.
- **Do NOT add live location, maps, or Redis.** Phase 3.
- **Do NOT duplicate anything already in `volt_core`.** Import it.
- **Do NOT modify the customer app** except where explicitly stated.
- Work on a branch. Tell me before pushing.

---

## Step 0 — Backend: expose vehicle types

The registration screen must offer vehicle types. Hardcoding them in Dart
duplicates server truth, which is the same mistake the fare estimator had.

Add `GET /api/v1/vehicle-types` — public, no auth. It is price-list data, and
customers see it in fare estimates anyway. Returns active types ordered by
`sort_order`: `code`, `label`, `capacity_kg`, `base_fare_paise`,
`included_km`, `per_km_paise`, `min_fare_paise`.

New Pydantic response schema. Tests: returns three seeded rows in
`sort_order`; excludes rows where `is_active` is false.

## Step 1 — Branch and scaffold

```powershell
cd $env:USERPROFILE\projects\volt
git checkout -b feat/driver-app
flutter create --org in.volt --platforms=android driver_app
```

That yields package `in.volt.driver_app`. The customer app is `in.volt.customer`,
so **rename to `in.volt.driver`** for consistency. Three places:

- `android/app/build.gradle.kts` — `namespace` and `applicationId`
- `android/app/src/main/kotlin/…/MainActivity.kt` — package declaration, and
  the directory path must match
- `AndroidManifest.xml` if it references the package

Verify with `findstr /i "applicationId namespace" driver_app\android\app\build.gradle.kts`.

Also set the app label to **"VOLT Driver"** in `AndroidManifest.xml`. Both apps
will be on the same phone and identical labels are genuinely confusing.

## Step 2 — Firebase for the driver app

Firebase console → your Volt project → ⚙ Project settings → **Add app** →
Android:

- Package name: `in.volt.driver`
- Nickname: VOLT Driver
- SHA-1: `3F:45:C2:2A:FB:2B:03:3E:8F:27:77:F1:12:42:F4:ED:B9:79:CB:86`

Skip the download and Gradle steps — `flutterfire` does both.

```powershell
cd $env:USERPROFILE\projects\volt\driver_app
flutterfire configure
```

Same project, **Android only**. It will register or find the `in.volt.driver`
app and generate `lib/firebase_options.dart`.

Phone auth and the test numbers are project-level, so they already work.

## Step 3 — Dependencies

`driver_app/pubspec.yaml`:

```yaml
dependencies:
  flutter:
    sdk: flutter
  volt_core:
    path: ../packages/volt_core
  flutter_riverpod: ^3.4.2
  firebase_core: ^<same as customer_app>
```

`dio` and `firebase_auth` come transitively through `volt_core`. Declare them
directly only if driver-app code imports them itself.

## Step 4 — Domain and data

**`driver_app/lib/features/driver/domain/driver_profile.dart`** — mirrors the
API's driver response: `id`, `phone`, `name`, `vehicleNumber`,
`vehicleTypeCode`, `isOnline`, `isVerified`, `rating`. With `fromJson`.

**`driver_app/lib/features/driver/domain/vehicle_type_option.dart`** — from
`GET /vehicle-types`: `code`, `label`, `capacityKg`.

**`driver_app/lib/features/jobs/domain/job.dart`** — a booking as the driver
sees it: `publicCode`, `status`, `pickupAddress`, `dropAddress`,
`goodsDescription`, `approxWeightKg`, `quotedFarePaise`, `quotedDistanceM`,
`quotedEtaMinutes`, `createdAt`. Plus a `quotedFareInr` getter.

**`driver_app/lib/features/driver/data/driver_repository.dart`** — interface
plus remote implementation over `ApiClient` from `volt_core`:

```dart
abstract interface class DriverRepository {
  Future<List<VehicleTypeOption>> vehicleTypes();

  /// Throws DriverNotRegistered on 403 "Not registered as a driver".
  Future<DriverProfile> me();

  Future<DriverProfile> register({
    required String name,
    required String vehicleNumber,
    required String vehicleTypeCode,
  });

  Future<DriverProfile> setOnline(bool online);

  Future<List<Job>> availableJobs();
  Future<List<Job>> myJobs();

  /// Throws JobAlreadyClaimed or JobExpired on 409.
  Future<Job> accept(String publicCode);

  Future<Job> markPickedUp(String publicCode);
  Future<Job> markDelivered(String publicCode);
}
```

The three exceptions matter. `ApiException` carries a status code and detail;
translate them into these named types at the repository boundary so screens
never inspect status codes. The expired-versus-claimed distinction exists on
the server precisely so the driver gets an honest message — do not collapse it.

## Step 5 — Providers

`driver_app/lib/features/driver/application/driver_providers.dart`:

- `apiClientProvider` — reuse `volt_core`'s if it exposes one; otherwise
  construct from `authTokenProvider`
- `driverRepositoryProvider`
- `driverProfileProvider` — `FutureProvider<DriverProfile?>`, null when the
  caller has no driver record (catch `DriverNotRegistered` and return null
  rather than letting it become an error state, since it is a routing signal)
- `availableJobsProvider` — `FutureProvider<List<Job>>`
- `activeJobProvider` — derived from `myJobs()`, the one in `driver_assigned`
  or `picked_up`, or null

**Accepting a job must be a `ref.read` inside the button handler, never a
provider.** Riverpod 3 auto-retries failed providers, and an auto-retried
accept would claim jobs the driver did not choose. Same reasoning as the
booking-creation note in `CLAUDE.md`.

## Step 6 — Routing

`main.dart` initialises Firebase then routes on three states:

```
session == null                    → PhoneEntryScreen
session != null, profile == null    → DriverRegistrationScreen
session != null, profile != null    → DriverHomeScreen
```

Because `driverProfileProvider` is async, the middle branch needs a loading
state — show a spinner, not a flash of the wrong screen.

Copy `phone_entry_screen.dart` and `otp_screen.dart` from the customer app and
adapt the copy. Spec 009 deliberately left them per-app; this is where you find
out whether they genuinely unify. **Report your judgement** on whether they
should move into `volt_core` — do not move them in this spec.

## Step 7 — Registration screen

`driver_app/lib/features/driver/presentation/driver_registration_screen.dart`

- Name — required, max 100
- Vehicle number — required. Indian plates vary in format enough that strict
  validation causes false rejections; require non-empty, uppercase it, cap at
  20 chars, and **do not** regex-match a plate pattern
- Vehicle type — dropdown from `vehicleTypes()`, showing label and capacity
- Submit → `register()` → invalidate `driverProfileProvider` so routing moves on

Form state is `setState`, not Riverpod. Disable submit while in flight.

## Step 8 — Home: availability and job board

`driver_app/lib/features/driver/presentation/driver_home_screen.dart`

Top: driver name, vehicle number and type, and an **online/offline switch**
calling `setOnline()`.

**Offline** — no job list. A clear "You're offline. Go online to see jobs."
The server returns 403 for `/jobs` when offline, so do not call it.

**Online, no active job** — the job board:

- Each card: fare in ₹, pickup → drop, goods description, weight, distance,
  ETA, and how long ago it was created
- Empty state: "No jobs right now" with a refresh button
- Pull-to-refresh, plus a manual refresh button
- **Accept** button per card

**Online, with an active job** — do not show the board at all. The server
enforces one active booking per driver; showing a board whose every Accept
would 409 is worse than not showing it.

## Step 9 — Accept, and losing the race

This is the screen that has to handle reality:

1. Tap Accept → button shows loading, all other Accepts disable
2. `await accept(publicCode)`
3. **Success** → navigate to the active job screen
4. **`JobAlreadyClaimed`** → SnackBar "Another driver took that job", refresh
   the board, stay put
5. **`JobExpired`** → SnackBar "That booking expired", refresh, stay put
6. **`ApiException`** → the message, with Retry

Do not navigate optimistically. Do not show a red error screen for 4 or 5 —
those are normal outcomes of a job board.

## Step 10 — Active job screen

`driver_app/lib/features/jobs/presentation/active_job_screen.dart`

Booking code, fare, pickup and drop addresses, goods, weight, and the customer's
phone number if the API exposes it. One primary action depending on status:

- `driver_assigned` → **"Picked up"** → `markPickedUp()`
- `picked_up` → **"Delivered"** → `markDelivered()`

After delivered, return to the job board with a confirmation.

Confirm destructive-ish transitions with a dialog — "Confirm pickup?" — because
these are irreversible and drivers tap phones one-handed.

If `driver_id` and the customer's phone are not currently in the API response,
say so rather than inventing fields; a driver who cannot contact the customer
is a real gap, and it may need a small backend addition.

## Step 11 — Run scripts

**`driver_app/run-prod.ps1`**
```powershell
flutter run -d RMX3371 --dart-define=API_BASE_URL=https://volt-api-951s.onrender.com
```

**`driver_app/run-local.ps1`** — same with `http://192.168.1.8:8000`, with a
comment noting the LAN IP is per-machine.

## Step 12 — The end-to-end test

Both apps on the same phone. Backend deployed. This is the whole point:

| Step | Expected |
|---|---|
| Driver app, sign in `7090909151` / `123456` | Lands on registration |
| Register: name, `KA 05 AB 1234`, Bike | Lands on home, offline |
| Go online | Job board, probably empty |
| Customer app: create a **Bike** booking | Real `VLT…` code, "Finding a driver" |
| Driver app: refresh | The booking appears |
| Accept | Active job screen |
| Customer app: manual refresh | Status now `driver_assigned` |
| Driver app: Picked up | Status updates |
| Customer app: refresh | `picked_up` |
| Driver app: Delivered | Back to board |
| Customer app: refresh | `delivered` |

Then the negative cases:

- Create a **Mini-Truck** booking → must **not** appear for a Bike driver
- Wait 6 minutes on an unclaimed booking, refresh the board → gone (expired)
- Accept a job, then try to accept another → blocked

Report the actual results, and be explicit about anything you did not verify
on device.

## Step 13 — Update `CLAUDE.md`

Driver app layout, package id `in.volt.driver`, the three-state routing, the
run scripts, and the note that accept must never live in a provider.

## Step 14 — Report and stop

1. Files created, and anything changed in `customer_app/` or the backend
2. The step 12 table with real results
3. Your judgement on whether the auth screens should move into `volt_core`
4. Any API gap you hit — missing fields, missing endpoints
5. Anything you were tempted to build beyond the spec, and did not

Do not push. Do not add polling.
