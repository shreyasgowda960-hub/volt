# Spec 009 — Extract the shared `volt_core` package

Build mode. **Pure refactor. Zero behaviour change.**

**Precondition:** spec 008 merged and deployed. `flutter analyze` clean,
`pytest` 88/88.

## New concepts introduced here

1. **Dart packages and path dependencies.** A package is a folder with its own
   `pubspec.yaml`. Apps depend on it with `path: ../packages/volt_core` —
   nothing is published anywhere, it is just code the compiler treats as a
   library with a public surface.
2. **Public API surface.** A package exports a barrel file
   (`lib/volt_core.dart`) listing what consumers may import. Anything not
   exported is internal. This is the first time your code has had a boundary
   that the compiler enforces.
3. **Generated code cannot be shared.** `firebase_options.dart` is generated
   per Firebase app, and the two apps are different Firebase apps. So
   `Firebase.initializeApp` stays in each app's `main.dart` and the package
   must never import `firebase_options.dart`. Getting this wrong makes the
   package depend on its consumer, which is backwards.
4. **Refactoring under an invariant.** The success criterion is not "it
   compiles" — it is "the customer app behaves exactly as before." That is a
   different and stricter bar, and it is why this spec is separate from
   building the driver app.

## Guardrails

- **Do NOT build the driver app.** That is spec 010.
- **Do NOT change any behaviour, error message, colour, or timeout value.**
  Moving code only.
- **Do NOT add dependencies** beyond what the package needs to declare for
  code it already contains.
- **Do NOT touch the backend.**
- Work on a branch. Tell me before pushing.

## Step 1 — Branch

```powershell
cd $env:USERPROFILE\projects\volt
git checkout -b refactor/volt-core-package
```

## Step 2 — Create the package

```powershell
cd $env:USERPROFILE\projects\volt
mkdir packages
cd packages
flutter create --template=package volt_core
```

Delete the generated `lib/volt_core.dart` stub content and the example test —
you will write real ones.

## Step 3 — What moves, and what does not

**Moves into `packages/volt_core/lib/src/`:**

| From `customer_app/lib/` | Reason |
|---|---|
| `core/config/app_config.dart` | Both apps read the same `API_BASE_URL` |
| `core/network/api_client.dart` | Auth interceptor and error translation — the code you least want two copies of |
| `core/theme/app_colors.dart` | One brand |
| `core/theme/app_theme.dart` | One brand |
| `features/auth/domain/volt_session.dart` | Same session shape |
| `features/auth/data/auth_repository.dart` | Same contract |
| `features/auth/data/fake_auth_repository.dart` | Useful in both for tests |
| `features/auth/data/firebase_auth_repository.dart` | Same OTP flow |
| `features/auth/data/auth_token_provider.dart` | Same token access |
| `features/auth/application/auth_providers.dart` | Both apps need identical auth state |

**Stays in `customer_app/`:**

- `main.dart` and `firebase_options.dart` — per-app Firebase identity
- Everything under `features/booking/` — customer-specific
- `features/auth/presentation/` — see the note below

**On the auth screens:** `phone_entry_screen.dart` and `otp_screen.dart` are
near-identical between the two apps, but the driver app's flow differs (a
driver who signs in without a registered profile needs a registration screen,
a customer does not). **Leave them in `customer_app/` for now.** Spec 010 will
show whether they genuinely unify or only look like they do. Premature UI
sharing is harder to undo than duplicated UI.

## Step 4 — `packages/volt_core/pubspec.yaml`

Declare only what the moved code actually imports: `flutter`,
`flutter_riverpod`, `dio`, `firebase_auth`. Use the same version constraints
as `customer_app/pubspec.yaml` — a mismatch produces a resolution conflict
that reads like an unrelated error.

Not `firebase_core` unless moved code imports it directly. Initialisation
stays in the apps.

## Step 5 — `packages/volt_core/lib/volt_core.dart`

The barrel file. Export exactly the public surface:

```dart
library volt_core;

export 'src/config/app_config.dart';
export 'src/network/api_client.dart';
export 'src/theme/app_colors.dart';
export 'src/theme/app_theme.dart';
export 'src/auth/auth_providers.dart';
export 'src/auth/auth_repository.dart';
export 'src/auth/auth_token_provider.dart';
export 'src/auth/fake_auth_repository.dart';
export 'src/auth/firebase_auth_repository.dart';
export 'src/auth/volt_session.dart';
```

Adjust paths to however you lay out `src/`. Flatten the
`domain/data/application` split inside the package — that structure exists to
organise a feature inside an app, and inside a small package it is just noise.

## Step 6 — Wire the customer app

In `customer_app/pubspec.yaml`:

```yaml
dependencies:
  volt_core:
    path: ../packages/volt_core
```

Then delete the moved files from `customer_app/lib/` and replace every import
of them with a single `import 'package:volt_core/volt_core.dart';`.

Expect this to touch every screen. `flutter analyze` will list them all.

```powershell
cd $env:USERPROFILE\projects\volt\customer_app
flutter pub get
flutter analyze
```

## Step 7 — The invariant check

`flutter analyze` passing proves nothing about behaviour. Verify on device:

```powershell
flutter run -d RMX3371 --dart-define=API_BASE_URL=https://volt-api-951s.onrender.com
```

Walk the whole flow and confirm each is **identical to before**:

| Check | Must be |
|---|---|
| Sign in with `7090909151` / `123456` | Works |
| Kill and reopen the app | Lands on home, session restored |
| Sign out, reopen | Phone screen |
| Colours, fonts, button shapes | Unchanged |
| Estimate loads, three fares | Same numbers |
| "Waking up the server" line after 5s | Still appears |
| Create a booking | Real `VLT…` code |
| Error state with WiFi off | Same message and Retry |

Any difference is a refactor bug, not an improvement. Report it rather than
keeping it.

## Step 8 — Package tests

Move any existing tests for the moved code into
`packages/volt_core/test/`. If none exist, add a small number covering the
public surface — `ApiClient`'s error translation (`DioException` → the right
`ApiException` message and status) is the highest-value target, since it is
shared, security-adjacent, and currently untested.

```powershell
cd $env:USERPROFILE\projects\volt\packages\volt_core
flutter test
```

## Step 9 — Update `CLAUDE.md`

Add the new repo layout including `packages/volt_core/`, state what lives in
the package versus the apps, and record the decision that auth *screens* stay
per-app until spec 010 proves they unify.

## Step 10 — Report and stop

1. Files moved, with old and new paths
2. Number of import sites changed in `customer_app/`
3. `flutter analyze` and `flutter test` results for both the app and the package
4. The step 7 table with actual results — and be explicit if you did not verify
   an item on device rather than implying you did
5. Anything you were tempted to improve while moving it, and did not

Do not push. Do not build the driver app.
