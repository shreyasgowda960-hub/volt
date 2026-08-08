# Spec 005 — Firebase phone auth + server token verification

Build mode. This spec closes the security hole spec 004 deliberately left open.

**Precondition:** Firebase project exists, Android app registered as
`in.volt.customer` with debug SHA-1 `3F:45:C2:2A:FB:2B:03:3E:8F:27:77:F1:12:42:F4:ED:B9:79:CB:86`,
Phone sign-in enabled, test number `+917090909151` / `123456` saved.

## Guardrails

- **Verify every Firebase API call against the installed package**, not against
  this spec. The code below is written from memory of the FlutterFire and
  firebase-admin APIs and may have details wrong — callback signatures,
  exception codes, method names. Read the actual package source or
  https://firebase.google.com/docs/auth/flutter/phone-auth and
  https://firebase.google.com/docs/auth/admin/verify-id-tokens, and correct the
  code where it differs. Flag anything you change.
- **The service account JSON is a real secret.** Unlike `google-services.json`,
  it grants admin access to the whole Firebase project. It must never be
  committed. Verify with `git status` before any commit.
- **Do NOT wire the Flutter app's booking screens to the API.** That is spec
  006. This spec swaps auth only.
- **Do NOT delete `FakeAuthRepository`.** It stays for tests and offline work.

---

# PART A — Client

## A1. Configure FlutterFire

```powershell
npm install -g firebase-tools
firebase login
dart pub global activate flutterfire_cli
cd $env:USERPROFILE\projects\volt\customer_app
flutterfire configure
```

Select the VOLT project. Select **Android only** — no iOS, web, macOS, or
Windows. This generates `lib/firebase_options.dart` and places
`android/app/google-services.json`, and adds the Gradle plugin wiring.

If `flutterfire` is not found after activation, add
`%LOCALAPPDATA%\Pub\Cache\bin` to your user PATH and open a new terminal.

## A2. Correct `.gitignore`

Remove these two lines from the repo-root `.gitignore`:

```
**/google-services.json
**/GoogleService-Info.plist
```

These are client identifiers, not secrets — they are extractable from any
published APK, and Firebase's security model assumes that. Excluding them just
breaks teammates' builds.

Add instead:

```
# Firebase Admin service account — REAL SECRET, grants project admin
volt-backend/secrets/
*-service-account.json
```

## A3. Add packages

```powershell
flutter pub add firebase_core firebase_auth
```

- **firebase_core** — initialises the connection; every Firebase package needs it
- **firebase_auth** — phone OTP

Nothing else. Not `cloud_firestore` (you have Postgres), not
`firebase_messaging` (phase 3).

## A4. Edit `customer_app/lib/main.dart`

Firebase must initialise before `runApp`:

```dart
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/theme/app_theme.dart';
import 'features/auth/application/auth_providers.dart';
import 'features/auth/presentation/phone_entry_screen.dart';
import 'features/booking/presentation/booking_home_screen.dart';
import 'firebase_options.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );
  runApp(const ProviderScope(child: VoltApp()));
}
```

`WidgetsFlutterBinding.ensureInitialized()` is required before any async work
that touches platform channels. Without it, `Firebase.initializeApp` throws.

The rest of the file is unchanged.

## A5. New file: `customer_app/lib/features/auth/data/firebase_auth_repository.dart`

```dart
import 'dart:async';

import 'package:firebase_auth/firebase_auth.dart';

import '../domain/volt_session.dart';
import 'auth_repository.dart';

/// Real phone auth. Slots in behind AuthRepository with no screen changes —
/// this is the payoff for the interface pattern.
class FirebaseAuthRepository implements AuthRepository {
  FirebaseAuthRepository({FirebaseAuth? auth})
      : _auth = auth ?? FirebaseAuth.instance;

  final FirebaseAuth _auth;

  @override
  Future<String> requestOtp(String phone) async {
    // verifyPhoneNumber is callback-based; the interface is Future-based.
    // A Completer bridges the two.
    final completer = Completer<String>();

    await _auth.verifyPhoneNumber(
      phoneNumber: phone,
      timeout: const Duration(seconds: 60),
      verificationCompleted: (PhoneAuthCredential credential) {
        // Android can auto-read the SMS and verify without user input.
        // Deliberately ignored: the OTP screen expects a verificationId and
        // handles the code itself. Revisit if auto-retrieval is wanted later.
      },
      verificationFailed: (FirebaseAuthException e) {
        if (!completer.isCompleted) completer.completeError(e);
      },
      codeSent: (String verificationId, int? resendToken) {
        if (!completer.isCompleted) completer.complete(verificationId);
      },
      codeAutoRetrievalTimeout: (String verificationId) {
        // Auto-retrieval window closed. Manual entry still works.
      },
    );

    return completer.future;
  }

  @override
  Future<VoltSession> verifyOtp({
    required String verificationId,
    required String phone,
    required String code,
  }) async {
    final credential = PhoneAuthProvider.credential(
      verificationId: verificationId,
      smsCode: code,
    );

    try {
      final result = await _auth.signInWithCredential(credential);
      final user = result.user;
      if (user == null) {
        throw StateError('Firebase returned no user after sign-in');
      }
      return VoltSession(
        userId: user.uid,
        phone: user.phoneNumber ?? phone,
      );
    } on FirebaseAuthException catch (e) {
      // VERIFY these codes against the installed package.
      if (e.code == 'invalid-verification-code' ||
          e.code == 'session-expired') {
        throw const InvalidOtpException();
      }
      rethrow;
    }
  }
}
```

## A6. Add token access — new file: `customer_app/lib/features/auth/data/auth_token_provider.dart`

```dart
import 'package:firebase_auth/firebase_auth.dart';

/// Supplies a fresh Firebase ID token for API calls.
///
/// The token is NOT stored on VoltSession on purpose: ID tokens expire after
/// one hour. Fetching per-request lets the SDK refresh transparently. A cached
/// token would start returning 401s an hour after sign-in.
abstract interface class AuthTokenProvider {
  Future<String?> currentToken();
}

class FirebaseAuthTokenProvider implements AuthTokenProvider {
  FirebaseAuthTokenProvider({FirebaseAuth? auth})
      : _auth = auth ?? FirebaseAuth.instance;

  final FirebaseAuth _auth;

  @override
  Future<String?> currentToken() async {
    final user = _auth.currentUser;
    if (user == null) return null;
    return user.getIdToken();
  }
}
```

## A7. Edit `customer_app/lib/features/auth/application/auth_providers.dart`

Swap the implementation and expose the token provider. This is the one-line
change the architecture was built for:

```dart
final authRepositoryProvider = Provider<AuthRepository>((ref) {
  return FirebaseAuthRepository();
});

final authTokenProvider = Provider<AuthTokenProvider>((ref) {
  return FirebaseAuthTokenProvider();
});
```

Keep `SessionNotifier` and `sessionProvider` exactly as they are.

## A8. Restore session on app start

Currently a restart logs the user out, because the session lives only in
memory. Firebase persists the sign-in, so read it back.

In `SessionNotifier.build()`, return a session derived from
`FirebaseAuth.instance.currentUser` when one exists, otherwise null. Keep it
synchronous — `currentUser` is available immediately after
`Firebase.initializeApp`.

Also add a `signOut()` that calls `FirebaseAuth.instance.signOut()` before
clearing state, or the user stays signed in at the Firebase level and gets
silently restored on next launch.

## A9. Remove the dev code hint

In `customer_app/lib/features/auth/presentation/otp_screen.dart`, delete the
widget that prints "dev build — the code is 123456", and the now-unused
`FakeAuthRepository` import.

**TEMPORARY, for A10 only:** add a debug print of the ID token immediately
after successful sign-in, so it can be copied for manual API testing:

```dart
assert(() {
  FirebaseAuth.instance.currentUser?.getIdToken().then(
        (t) => debugPrint('ID_TOKEN=$t'),
      );
  return true;
}());
```

Wrapping it in `assert` means it is stripped from release builds entirely.
Delete it once spec 006 lands.

## A10. Verify the client

```powershell
flutter run -d RMX3371
```

- Enter `7090909151` → Continue
- No real SMS arrives (test number). Enter `123456` → Verify
- Home screen shows `+917090909151`
- **Kill the app and reopen** — it should land on the home screen, not the
  phone screen. That proves A8 works.
- Sign out → phone screen. Reopen → still phone screen.
- Wrong code → the error path still renders
- Copy the `ID_TOKEN=` value from the `flutter run` console. Needed for Part B.

Check Firebase console → Authentication → Users. A user row should exist with
that phone number.

---

# PART B — Server

## B1. Service account key

Firebase console → ⚙ Project settings → **Service accounts** tab → Generate
new private key → download.

Save to `volt-backend/secrets/firebase-service-account.json`.

**This grants admin access to the entire Firebase project.** Confirm
`git status` does not list it before any commit. If it ever leaks, revoke it in
the same console screen immediately.

## B2. Add the dependency

Add to `volt-backend/requirements.txt`:

```
firebase-admin
```

Then `pip install -r requirements.txt`.

What it does: verifies the cryptographic signature on ID tokens against
Google's public keys, so the server can trust who the caller is. Client-side
sign-in proves nothing to the server on its own.

## B3. Edit `volt-backend/app/config.py`

Add:

```python
    firebase_credentials_path: str = "secrets/firebase-service-account.json"
```

And add to both `.env` and `.env.example`:

```
FIREBASE_CREDENTIALS_PATH=secrets/firebase-service-account.json
```

## B4. New file: `volt-backend/app/auth.py`

```python
import firebase_admin
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.database import get_db
from app.models.user import User

_bearer = HTTPBearer(auto_error=True)


def init_firebase() -> None:
    """Idempotent. Called once at app startup."""
    if not firebase_admin._apps:
        cred = credentials.Certificate(get_settings().firebase_credentials_path)
        firebase_admin.initialize_app(cred)


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Verifies the Firebase ID token and returns the matching User row,
    creating it on first sign-in.

    This is the only trustworthy source of caller identity. Nothing from the
    request body is ever used to decide who the caller is.
    """
    try:
        # verify_id_token is blocking (network call to fetch Google's public
        # keys, though they are cached). Off the event loop it goes.
        decoded = await run_in_threadpool(
            firebase_auth.verify_id_token, creds.credentials
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    uid = decoded.get("uid")
    phone = decoded.get("phone_number")
    if not uid or not phone:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing uid or phone_number",
        )

    result = await db.execute(select(User).where(User.firebase_uid == uid))
    user = result.scalar_one_or_none()

    if user is None:
        # A user row may already exist from pre-auth testing — link it rather
        # than creating a duplicate, since phone is unique.
        result = await db.execute(select(User).where(User.phone == phone))
        user = result.scalar_one_or_none()
        if user is not None:
            user.firebase_uid = uid
        else:
            user = User(phone=phone, firebase_uid=uid)
            db.add(user)
        await db.commit()
        await db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled"
        )

    return user
```

## B5. Edit `volt-backend/app/main.py`

Call `init_firebase()` at startup, before the app serves requests. Use a
lifespan context manager rather than the deprecated `@app.on_event("startup")`.

## B6. Edit `volt-backend/app/schemas/booking.py`

**Delete** `customer_phone` from `BookingCreate` entirely, along with its
SECURITY comment. Identity now comes from the token.

## B7. Edit `volt-backend/app/services/booking.py`

- Delete `get_or_create_user` — `get_current_user` owns that now
- `create_booking` takes a `user: User` parameter instead of reading a phone
  from the payload
- Remove the SECURITY comments that no longer apply

## B8. Edit `volt-backend/app/routers/bookings.py`

- `POST /estimate` — **leave unauthenticated.** Price discovery before sign-in
  is normal, it creates nothing, and it exposes no user data.
- `POST /bookings` — add `user: User = Depends(get_current_user)`, pass to the
  service
- `GET /bookings/{public_code}` — add the same dependency, and after loading
  the booking:

```python
    if found is None or found.customer_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )
```

**404, not 403.** A 403 confirms the booking exists and belongs to someone
else, which lets an attacker enumerate valid codes. 404 reveals nothing.

Delete every remaining `# SECURITY: spec 005` comment — grep to confirm none
survive.

## B9. Verify the server

```powershell
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs`. There should now be an **Authorize** button.
Paste the ID token from A10 into it.

Confirm each:

| Test | Expected |
|---|---|
| POST `/estimate` with no token | 200, three fares |
| POST `/bookings` with no token | 403 or 401 |
| POST `/bookings` with a garbage token | 401 |
| POST `/bookings` with the real token, no `customer_phone` field | 201 |
| GET that booking with the same token | 200 |
| GET that booking with no token | 401 |
| GET a booking belonging to another user | 404, not 403 |

For the last one: create a second user row manually in psql, reassign a
booking's `customer_id` to it, then fetch with your token.

Then confirm the linkage:

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -U postgres -d volt_dev -c "SELECT id, phone, firebase_uid FROM users;"
```

Your user should have a non-null `firebase_uid`.

## B10. Tests

Add to `tests/`:

- `get_current_user` with an invalid token raises 401 (mock
  `verify_id_token` to raise)
- `get_current_user` with a valid token for an unknown uid creates a user
- `get_current_user` with a valid token whose phone matches an existing row
  links `firebase_uid` rather than creating a duplicate

Mock `firebase_auth.verify_id_token` — never call Firebase in tests.

## B11. Update `CLAUDE.md`

Replace the "NOT AUTHENTICATED" warning with:

```
Auth: Firebase phone OTP end to end. Client uses FirebaseAuthRepository behind
the AuthRepository interface. Server verifies ID tokens via firebase-admin;
get_current_user is the only source of caller identity. Bookings enforce
ownership and return 404 (not 403) for another user's booking.
POST /bookings/estimate stays public by design.
Service account key at volt-backend/secrets/ — gitignored, never commit.
```

## B12. Report and stop

1. Files created, edited, deleted
2. Every Firebase API call where this spec's code differed from the real
   package, and what you changed
3. The verification table from B9, with actual status codes
4. Test results
5. Confirmation that `git status` does not list the service account JSON, and
   that no `# SECURITY: spec 005` comments remain

Do not wire the app's booking screens to the API — that is spec 006.
